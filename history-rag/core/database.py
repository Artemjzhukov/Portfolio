import os
from typing import List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator
from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams
from langchain_community.embeddings import HuggingFaceEmbeddings

load_dotenv()

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "history_docs")
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)


# ---------------------------------------------------------------------------
# 1. Pydantic schema — validates a document BEFORE it reaches the vector store
# ---------------------------------------------------------------------------

class HistoricalDocument(BaseModel):
    """Schema for a single source document before ingestion into Qdrant."""

    content: str = Field(..., min_length=1, description="Raw text of the document/chunk.")
    source: str = Field(..., min_length=1, description="Origin file name or reference, e.g. 'alexander_ii_notes.docx'.")
    topic: Optional[str] = Field(default=None, description="Historical topic/tag, e.g. 'Alexander II'.")
    doc_date: Optional[str] = Field(
        default=None,
        description="Date the source material refers to (free text — historical dates vary in precision, e.g. '1861' or 'circa 1860s').",
    )

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content must not be empty or whitespace-only")
        return v


class VectorDimensionConflict(Exception):
    """Raised only if automatic resolution itself is impossible (should be rare)."""


# ---------------------------------------------------------------------------
# 2. Automated vector-dimension conflict resolution
# ---------------------------------------------------------------------------

def _get_embeddings() -> HuggingFaceEmbeddings:
    return HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)


def _probe_embedding_dimension(embeddings: HuggingFaceEmbeddings) -> int:
    """
    Discovers the active embedding model's vector size at runtime by embedding
    a throwaway string, instead of hardcoding a number that has to be updated
    by hand every time EMBEDDING_MODEL changes.
    """
    probe_vector = embeddings.embed_query("dimension probe")
    return len(probe_vector)


def _resolve_collection_name(client: QdrantClient, base_name: str, active_dim: int) -> str:
    """
    Ensures we never write vectors of the wrong size into an existing collection.

    If `base_name` doesn't exist yet -> use it as-is.
    If it exists and its vector size matches the active embedding model -> reuse it.
    If it exists with a DIFFERENT vector size (e.g. someone swapped EMBEDDING_MODEL
    since the collection was created) -> route to a dimension-suffixed collection
    name instead of silently reusing it (which Qdrant would reject at insert time)
    or deleting the old data.
    """
    existing_names = [c.name for c in client.get_collections().collections]

    if base_name not in existing_names:
        return base_name

    collection_info = client.get_collection(base_name)
    existing_dim = collection_info.config.params.vectors.size

    if existing_dim == active_dim:
        return base_name

    versioned_name = f"{base_name}_dim{active_dim}"
    print(
        f"[dimension conflict] Collection '{base_name}' exists with vector size "
        f"{existing_dim}, but the active embedding model '{EMBEDDING_MODEL}' "
        f"produces size {active_dim}. Using '{versioned_name}' instead, so existing "
        f"data isn't overwritten and inserts don't fail."
    )
    return versioned_name


def get_vector_store() -> QdrantVectorStore:
    """
    Returns a QdrantVectorStore wired to a collection whose vector size matches
    the currently configured embedding model. Conflicts between an existing
    collection and a newly configured embedding model are resolved automatically
    (see _resolve_collection_name) instead of requiring manual recreation.
    """
    try:
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        client.get_collections()
    except Exception as e:
        raise ConnectionError(
            f"Could not connect to Qdrant at {QDRANT_HOST}:{QDRANT_PORT}. "
            f"Make sure the server is running. Original error: {e}"
        )

    embeddings = _get_embeddings()
    active_dim = _probe_embedding_dimension(embeddings)

    collection_name = _resolve_collection_name(client, COLLECTION_NAME, active_dim)

    existing_names = [c.name for c in client.get_collections().collections]
    if collection_name not in existing_names:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=active_dim, distance=Distance.COSINE),
        )
        print(f"Collection '{collection_name}' created (dim={active_dim}).")

    return QdrantVectorStore(client=client, collection_name=collection_name, embedding=embeddings)


# ---------------------------------------------------------------------------
# 3. Ingestion — validates first, then attaches metadata for future citations
# ---------------------------------------------------------------------------

def add_documents_to_store(raw_documents: List[dict]) -> None:
    """
    Validates raw documents against HistoricalDocument before they ever reach
    the vector store. Rejects the whole batch with a clear, itemized error if
    any document fails validation, rather than silently ingesting bad data.

    Also attaches source/topic/date as metadata on the resulting LangChain
    Documents — this doesn't wire up citations in the answer yet (that's a
    separate, still-open piece of work), but it means the data needed for
    citations is captured at ingestion time rather than lost.
    """
    validated: List[HistoricalDocument] = []
    errors: List[str] = []

    for i, raw in enumerate(raw_documents):
        try:
            validated.append(HistoricalDocument(**raw))
        except Exception as e:
            errors.append(f"  - item {i}: {e}")

    if errors:
        raise ValueError(
            f"Rejected {len(errors)} of {len(raw_documents)} documents due to "
            f"schema validation errors:\n" + "\n".join(errors)
        )

    lc_documents = [
        Document(
            page_content=doc.content,
            metadata={"source": doc.source, "topic": doc.topic, "date": doc.doc_date},
        )
        for doc in validated
    ]

    vector_store = get_vector_store()
    vector_store.add_documents(lc_documents)
    print(f"Added {len(lc_documents)} validated documents to the vector store.")