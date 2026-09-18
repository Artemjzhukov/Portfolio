"""Хранилище эталонных ответов: data/answer_keys/{subject_id}.json.

Приоритет (фаза 5, п.2): payload.answer_key (явное переопределение от n8n)
> файл хранилища > пусто. n8n больше не обязан передавать answer_key.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.schemas import AnswerKeyFile

logger = logging.getLogger(__name__)


class AnswerKeyStore:
    def __init__(self, settings) -> None:
        self.s = settings

    def get(self, subject_id: str) -> dict[str, str]:
        path = Path(self.s.answer_keys_dir) / f"{subject_id}.json"
        if not path.is_file():
            return {}
        data = AnswerKeyFile.model_validate_json(path.read_text(encoding="utf-8"))
        if data.subject_id != subject_id:
            raise ValueError(
                f"{path}: subject_id в файле ('{data.subject_id}') != ожидаемому ('{subject_id}')"
            )
        return dict(data.answers)


def resolve_answer_key(payload, store: AnswerKeyStore | None) -> dict[str, str]:
    """Payload побеждает файл: явное указание в запросе — сильнее стора."""
    if payload.answer_key:
        return dict(payload.answer_key)
    if store is not None:
        return store.get(payload.subject_id)
    return {}
