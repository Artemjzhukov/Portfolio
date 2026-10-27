"""Общие фикстуры: FakeLLM, настройки, минимальная рубрика."""

from __future__ import annotations

import io
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
        (BASE_DIR / "data" / "criteria" / "history" / "task_19_2025.json").read_text("utf-8")
    )


# ---------------------------------------------------------------------------
# Фабрики legacy-форматов: собирают настоящие RTF/DOCX байты, а не заглушки,
# чтобы тесты извлечения проверяли реальные парсеры (striprtf, python-docx).
# ---------------------------------------------------------------------------

def build_rtf(body: str, codepage: int | None = 1251, body_codec: str = "cp1251") -> bytes:
    """Минимальный RTF так, как его пишет Word: заголовок с \\ansicpgN + \\'hh-escape'ы.

    Не-ASCII символы кодируются байтами указанной кодировки и экранируются:
    «сырые» 8-битные байты внутри RTF недопустимы.
    """
    header = "{\\rtf1\\ansi"
    if codepage is not None:
        header += f"\\ansicpg{codepage}"
    header += "\\deff0{\\fonttbl{\\f0 Times New Roman;}}\n"
    encoded = body.encode(body_codec)
    escaped = "".join(
        ch if ord(ch) < 128 else "\\'" + format(byte, "02x")
        for ch, byte in zip(body, encoded)
    )
    return (header + escaped + "}").encode("ascii")


def build_docx(paragraphs: list[str], table: list[list[str]] | None = None) -> bytes:
    """DOCX через python-docx: абзацы + опциональная таблица (бланки ответов)."""
    from docx import Document as DocxDocument

    document = DocxDocument()
    for text in paragraphs:
        document.add_paragraph(text)
    if table:
        doc_table = document.add_table(rows=len(table), cols=len(table[0]))
        for row_index, row in enumerate(table):
            for col_index, value in enumerate(row):
                doc_table.cell(row_index, col_index).text = value
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def make_rtf():
    return build_rtf


@pytest.fixture
def make_docx():
    return build_docx
