"""RAG gap-analysis: Qdrant-рекомендации тем для повторения (на русском).

Компонент ВСПОМОГАТЕЛЬНЫЙ: недоступность Qdrant/эмбеддингов не должна
ронять оценку — возвращаются пустые рекомендации с причиной.
Инициализация эмбеддингов (torch) — ленивая, один раз на процесс.
"""

from __future__ import annotations

import logging

from app.config import Settings
from app.schemas import RAGChunk, RAGRecommendation

logger = logging.getLogger(__name__)


class FactChecker:
    """Проверка фактических утверждений по хранилищу (для ЕГЭ-оценщика)."""

    def __init__(self, retriever: "TheoryRetriever") -> None:
        self.retriever = retriever

    def check(self, quote: str, topics: list[str]) -> str | None:
        """Returns: релевантный фрагмент хранилища или None, если не подтверждено."""
        query = f"{quote} {' '.join(topics)}".strip()
        chunks = self.retriever.search("history", query, k=2)
        if not chunks:
            return None
        return chunks[0].text


class TheoryRetriever:
    """Поиск теории в Qdrant-коллекции с материалами предмета."""

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self._ready: bool | None = None
        self._store = None
        self._unavailable_reason = ""

    # ------------------------------------------------------------------

    def _ensure_ready(self) -> bool:
        """Ленивая инициализация. Отрицательный результат НЕ кэшируется навсегда:
        первый вызов может случиться раньше готовности Qdrant (race с depends_on),
        поэтому следующая попытка повторяется, а не блокируется до рестарта."""
        if self._ready:
            return True
        try:
            from langchain_community.embeddings import HuggingFaceEmbeddings
            from langchain_qdrant import QdrantVectorStore
            from qdrant_client import QdrantClient
            from qdrant_client.http.models import Distance, VectorParams

            embeddings = HuggingFaceEmbeddings(model_name=self.s.embedding_model)
            client = QdrantClient(host=self.s.qdrant_host, port=self.s.qdrant_port)
            client.get_collections()

            # Чистый volume (первый запуск compose) -> коллекции нет -> 404 при
            # инициализации стора. Создаём сами, как core/database.py.
            if not client.collection_exists(self.s.qdrant_collection):
                dim = len(embeddings.embed_query("dimension probe"))
                client.create_collection(
                    collection_name=self.s.qdrant_collection,
                    vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
                )
                logger.info(
                    "Коллекция '%s' создана (dim=%d). Пустая — залейте корпус материала "
                    "(core/database.add_documents_to_store), иначе рекомендации будут пустыми.",
                    self.s.qdrant_collection, dim,
                )

            self._store = QdrantVectorStore(
                client=client,
                collection_name=self.s.qdrant_collection,
                embedding=embeddings,
            )
            self._ready = True
        except Exception as exc:
            self._unavailable_reason = (
                f"RAG недоступен (Qdrant {self.s.qdrant_host}:{self.s.qdrant_port}): {exc}"
            )
            logger.warning(self._unavailable_reason)
        return self._ready is True

    # ------------------------------------------------------------------

    def search(self, subject_id: str, query: str, k: int | None = None) -> list[RAGChunk]:
        """Векторный поиск по коллекции. Пустой список, если сервис недоступен."""
        if not self._ensure_ready():
            return []
        top_k = k or self.s.rag_top_k
        try:
            docs = self._store.similarity_search_with_score(query, k=top_k)
        except Exception as exc:
            logger.warning("Ошибка поиска в Qdrant: %s", exc)
            self._unavailable_reason = f"Ошибка поиска в Qdrant: {exc}"
            return []
        chunks: list[RAGChunk] = []
        for doc, score in docs:
            similarity = 1.0 - float(score) if float(score) > 1.0 else float(score)
            chunks.append(
                RAGChunk(
                    text=doc.page_content,
                    source=doc.metadata.get("source"),
                    topic=doc.metadata.get("topic"),
                    score=max(0.0, min(1.0, similarity)),
                )
            )
        return chunks

    def recommend(self, subject_id: str, task_number, query_text: str) -> RAGRecommendation:
        """Рекомендации для задачи, где потеряны баллы."""
        rec = RAGRecommendation(task_number=task_number, query_text=query_text)
        if not self._ensure_ready():
            rec.unavailable_reason = self._unavailable_reason
            return rec
        chunks = self.search(subject_id, query_text)
        relevant = [c for c in chunks if c.score >= self.s.rag_min_score]
        rec.chunks = relevant
        if relevant:
            lines = ["**Что повторить:**"]
            for c in relevant[: self.s.rag_top_k]:
                where = c.topic or c.source or "материалы курса"
                excerpt = " ".join(c.text.split())[:180]
                lines.append(f"- {where}: {excerpt}…")
            rec.recommended_topics = "\n".join(lines)
        else:
            rec.recommended_topics = (
                "Релевантные материалы в базе не найдены — повторите тему задания по учебнику."
            )
        return rec
