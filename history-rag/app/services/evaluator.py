"""Фасад оценки ученика: делегирует существующему AssessmentPipeline и сохраняет прогресс.

pipeline.py остаётся источником истины для пайплайна (извлечение -> проверка ->
RAG -> AssessmentResult). Этот модуль только: вызывает pipeline ровно один раз,
маппит итог в EvaluationRecord через EvaluationRecord.from_assessment и пишет
его в JobStore.save_result. Нового обращения к LLM/Qdrant здесь нет.
"""

from __future__ import annotations

import logging

from app.jobs import JobStore
from app.schemas import AssessmentResult, EvaluationRecord, SubmissionInput

logger = logging.getLogger(__name__)


class StudentEvaluator:
    """Тонкий фасад: pipeline + сохранение прогресса."""

    def __init__(self, *, pipeline, store: JobStore, key_store=None) -> None:
        if not callable(getattr(pipeline, "run", None)):
            raise TypeError("StudentEvaluator требует pipeline с методом run(...)")
        if not isinstance(store, JobStore):
            raise TypeError("StudentEvaluator требует store: JobStore")
        self.pipeline = pipeline
        self.store = store
        self.key_store = key_store

    def evaluate(
        self,
        payload_dict: dict,
        file_bytes: bytes,
        file_name: str | None,
        *,
        job_id: str,
        test_name: str | None = None,
    ) -> AssessmentResult:
        """Один вызов pipeline.run, затем сохранение EvaluationRecord.

        Args:
            payload_dict: сырой вход SubmissionInput (валидируется один раз здесь).
            test_name: явное test_name перекрывает payload.test_name для заголовка.
        """
        payload = SubmissionInput(**payload_dict)
        result = self.pipeline.run(payload, file_bytes, file_name, job_id=job_id)
        record = EvaluationRecord.from_assessment(
            job_id, result, test_name=test_name if test_name is not None else payload.test_name
        )
        self.store.save_result(record)
        logger.info("job=%s evaluated via facade: total=%g/%g", job_id, result.total_score, result.max_possible_score)
        return result