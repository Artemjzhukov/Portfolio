"""Общие фикстуры: FakeLLM, настройки, минимальная рубрика."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config import Settings  # noqa: E402
from app.schemas import TaskRubric  # noqa: E402


class FakeLLM:
    """Подмена LLMClient: отдаёт заготовленные ответы по очереди."""

    def __init__(self, responses=None, model="fake-model") -> None:
        self.responses = list(responses or [])
        self.calls: list[dict] = []
        self.model = model

    def chat(self, *, system, user, schema, schema_name, **kwargs) -> dict:
        self.calls.append({"system": system, "user": user, "schema_name": schema_name})
        if not self.responses:
            raise AssertionError("неожиданный вызов LLM в тесте")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def settings() -> Settings:
    return Settings(
        llm_provider="openai",
        openai_api_key="test-key",
        criteria_dir=Path("data/criteria"),
        qdrant_host="localhost",
        qdrant_port=6333,
    )


@pytest.fixture
def rubric_task19() -> TaskRubric:
    return TaskRubric.model_validate_json(
        (BASE_DIR / "data" / "criteria" / "history" / "task_19.json").read_text("utf-8")
    )
