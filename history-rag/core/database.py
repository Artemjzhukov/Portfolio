import os
import uuid
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
    image: Optional[str] = Field(
        default=None,
        description="Относительный путь к изображению в data/media (напр. 'reforms/portret.jpg'). "
        "Для фото/карт: вектор строится по подписи, файл лежит отдельно и раздаётся через /media.",
    )
    source_format: Optional[str] = Field(
        default=None,
        description="Расширение исходного файла без точки: 'docx', 'pdf', 'rtf', 'txt'.",
    )
    detected_format: Optional[str] = Field(
        default=None,
        description="Формат по магическим байтам ('docx', 'rtf', 'doc_legacy', 'unknown'), "
        "а не по расширению — расширение в корпусе врёт (14 .docx нулевого размера).",
    )
    encoding: Optional[str] = Field(
        default=None,
        description="Кодировка, которой файл фактически прочитан (для RTF — из \\ansicpgN).",
    )
    sha256: Optional[str] = Field(
        default=None,
        description="SHA-256 исходного файла: позволяет находить дубликаты между папками корпуса.",
    )

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content must not be empty or whitespace-only")
        return v


# Fixed namespace so point ids are stable across processes and machines: the same
# file ingested twice must map onto the same Qdrant points (upsert, not duplicate).
ID_NAMESPACE = uuid.UUID("6f5f6f2a-1c1e-4f3a-9c1a-2f9f0b7e5d31")


def document_point_id(source: str, content: str) -> str:
    """Deterministic Qdrant point id derived from (source, content).

    Qdrant accepts only UUID or unsigned-int ids, hence uuid5 over a hash-like
    name. Source is part of the key so identical text in two different files
    keeps two distinct points instead of collapsing into one.
    """
    return str(uuid.uuid5(ID_NAMESPACE, f"{source}\x1f{content}"))


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

def add_documents_to_store(
    raw_documents: List[dict],
    *,
    ids: Optional[List[str]] = None,
    vector_store: Optional[QdrantVectorStore] = None,
) -> List[str]:
    """
    Validates raw documents against HistoricalDocument before they ever reach
    the vector store. Rejects the whole batch with a clear, itemized error if
    any document fails validation, rather than silently ingesting bad data.

    Point ids are deterministic (see document_point_id) and passed explicitly to
    `add_documents(ids=...)`, which Qdrant applies as an upsert. Re-running the
    ingestion over the same corpus therefore rewrites the same points instead of
    appending duplicates — this is what makes the upload idempotent.

    `vector_store` is an injection seam for tests: without it the function would
    open a real Qdrant connection and build HuggingFace embeddings, which makes
    an idempotency test impossible to run offline.

    Returns the point ids that were written, in document order.
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

    if ids is not None and len(ids) != len(validated):
        raise ValueError(
            f"ids length mismatch: expected {len(validated)} ids, got {len(ids)}"
        )

    lc_documents = [
        Document(
            page_content=doc.content,
            metadata={
                "source": doc.source,
                "topic": doc.topic,
                "date": doc.doc_date,
                "image": doc.image,
                "source_format": doc.source_format,
                "detected_format": doc.detected_format,
                "encoding": doc.encoding,
                "sha256": doc.sha256,
            },
        )
        for doc in validated
    ]

    point_ids = (
        list(ids) if ids is not None
        else [document_point_id(doc.source, doc.content) for doc in validated]
    )

    store = vector_store if vector_store is not None else get_vector_store()
    store.add_documents(lc_documents, ids=point_ids)
    print(f"Added {len(lc_documents)} validated documents to the vector store.")
    return point_ids