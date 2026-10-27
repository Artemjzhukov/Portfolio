"""Идемпотентность ингеста: повторная загрузка того же корпуса не плодит дубли.

Проверка идёт против настоящего Qdrant в режиме ``:memory:`` (qdrant-client),
а не против мока: сравниваются фактическое число точек и фактический набор ID
после двух загрузок одного и того же набора документов.
"""

from __future__ import annotations

import pytest
from langchain_core.embeddings import FakeEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams

from core.database import add_documents_to_store, document_point_id

COLLECTION = "test_history_docs"
DIM = 16

RAW_DOCUMENTS = [
    {
        "content": "Смутное время началось после пресечения династии Рюриковичей.",
        "source": "smuta.docx#1",
        "topic": "Смута",
        "doc_date": "1598",
        "source_format": "docx",
        "detected_format": "docx",
        "encoding": None,
        "sha256": "a" * 64,
    },
    {
        "content": "Ополчение Минина и Пожарского освободило Москву в 1612 году.",
        "source": "smuta.docx#2",
        "topic": "Смута",
        "doc_date": "1612",
        "source_format": "docx",
        "detected_format": "docx",
        "encoding": None,
        "sha256": "a" * 64,
    },
    {
        "content": "Крестоцеловальная запись Василия Шуйского ограничила самодержавие.",
        "source": "zapis.rtf#1",
        "topic": "Смута",
        "doc_date": "1606",
        "source_format": "rtf",
        "detected_format": "rtf",
        "encoding": "cp1251",
        "sha256": "b" * 64,
    },
]


@pytest.fixture
def store() -> QdrantVectorStore:
    client = QdrantClient(location=":memory:")
    client.create_collection(
        COLLECTION, vectors_config=VectorParams(size=DIM, distance=Distance.COSINE)
    )
    return QdrantVectorStore(
        client=client, collection_name=COLLECTION, embedding=FakeEmbeddings(size=DIM)
    )


def point_count(store: QdrantVectorStore) -> int:
    return store.client.count(COLLECTION).count


def point_ids(store: QdrantVectorStore) -> set[str]:
    points, _ = store.client.scroll(COLLECTION, limit=1000)
    return {str(point.id) for point in points}


def payloads(store: QdrantVectorStore) -> list[dict]:
    """Payload точек в том виде, в каком его кладёт langchain_qdrant."""
    points, _ = store.client.scroll(COLLECTION, limit=1000, with_vectors=False)
    return [dict(point.payload or {}) for point in points]


def payload_metadata(store: QdrantVectorStore) -> list[dict]:
    """Метаданные документов: langchain_qdrant хранит их вложенно, в поле metadata."""
    return [payload["metadata"] for payload in payloads(store)]


class TestIdempotentIngestion:
    def test_second_upload_keeps_same_points(self, store, capsys):
        first_ids = add_documents_to_store(RAW_DOCUMENTS, vector_store=store)
        count_after_first = point_count(store)
        ids_after_first = point_ids(store)

        second_ids = add_documents_to_store(RAW_DOCUMENTS, vector_store=store)
        count_after_second = point_count(store)
        ids_after_second = point_ids(store)

        with capsys.disabled():
            print()
            print(f"  загрузка #1: count={count_after_first}, ids={len(ids_after_first)}")
            print(f"  загрузка #2: count={count_after_second}, ids={len(ids_after_second)}")
            print(f"  наборы ID идентичны: {ids_after_first == ids_after_second}")
            for point_id in sorted(ids_after_first):
                print(f"    {point_id}")

        assert first_ids == second_ids
        assert count_after_first == len(RAW_DOCUMENTS)
        assert count_after_second == count_after_first
        assert ids_after_second == ids_after_first

    def test_metadata_reaches_payload(self, store):
        add_documents_to_store(RAW_DOCUMENTS, vector_store=store)
        raw_payloads = payloads(store)
        # Контракт хранения langchain_qdrant: текст и метаданные лежат раздельно.
        assert all(set(payload) == {"page_content", "metadata"} for payload in raw_payloads)
        by_source = {item["source"]: item for item in payload_metadata(store)}
        rtf = by_source["zapis.rtf#1"]
        assert rtf["source_format"] == "rtf"
        assert rtf["detected_format"] == "rtf"
        assert rtf["encoding"] == "cp1251"
        docx = by_source["smuta.docx#1"]
        assert docx["sha256"] == "a" * 64
        assert docx["topic"] == "Смута"
        assert docx["date"] == "1598"

    def test_ids_depend_on_source_and_content(self):
        base = document_point_id("doc.docx#1", "текст")
        assert base == document_point_id("doc.docx#1", "текст")
        assert base != document_point_id("doc.docx#2", "текст")
        assert base != document_point_id("other.docx#1", "текст")
        assert base != document_point_id("doc.docx#1", "другой текст")

    def test_explicit_ids_are_used(self, store):
        ids = [document_point_id("x", f"chunk-{i}") for i in range(len(RAW_DOCUMENTS))]
        returned = add_documents_to_store(RAW_DOCUMENTS, ids=ids, vector_store=store)
        assert returned == ids
        assert point_ids(store) == set(ids)

    def test_ids_length_mismatch_rejected(self, store):
        with pytest.raises(ValueError, match="ids length mismatch"):
            add_documents_to_store(RAW_DOCUMENTS, ids=["one"], vector_store=store)

    def test_blank_content_rejected_before_store(self, store):
        with pytest.raises(ValueError, match="Rejected 1 of 1"):
            add_documents_to_store(
                [{"content": "   ", "source": "x.txt#1"}], vector_store=store
            )
        assert point_count(store) == 0
