"""Извлечение текста работы ученика: PDF/DOCX напрямую, изображения и сканы — Vision OCR.

Двухступенчатый подход (защита от «произвольного порядка» ответов):
1. Vision-модель только ТРАНСКРИБИРУЕТ фрагменты в строгий JSON (без интерпретации).
2. Привязка к номерам задач и merge — детерминированно, в коде.
"""

from __future__ import annotations

import io
import re
from typing import Optional

from pypdf import PdfReader

from app.config import Settings
from app.schemas import ExtractedSubmission, OCRSegment, SourceType
from app.services.llm import LLMClient

IMAGE_MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}

OCR_SYSTEM_PROMPT = (
    "Ты — транскрибатор рукописных работ на русском языке. ТВОЯ ЗАДАЧА — ТОЛЬКО РАСПОЗНАВАНИЕ, "
    "НЕ ОЦЕНИВАНИЕ И НЕ ИНТЕРПРЕТАЦИЯ.\n"
    "Правила:\n"
    "1. Разбей работу на фрагменты по номерам задач. Номер задачи бери ТОЛЬКО если он написан на листе.\n"
    "2. Если номер задачи не читается или не указан — верни task_number: null. НЕ УГАДЫВАЙ номер.\n"
    "3. Сохраняй текст ответа дословно, включая ошибки ученика. Не исправляй, не дополняй, не оценивай.\n"
    "4. Для каждой записи укажи страницу и уверенность распознавания (0.0-1.0).\n"
    "5. Никогда не придумывай ответы, которых нет на изображении."
)

OCR_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["pages_count", "segments"],
    "properties": {
        "pages_count": {"type": "integer", "minimum": 1},
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["task_number", "text", "page", "confidence"],
                "properties": {
                    "task_number": {"type": ["integer", "null"], "minimum": 1, "maximum": 40},
                    "text": {"type": "string", "minLength": 1},
                    "page": {"type": "integer", "minimum": 1},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        },
    },
}

# Привязка номеров задач — только по регэкспам в начале строки, чтобы
# «1861 год» не превратился в задачу 61.
_TASK_LINE_PATTERNS = [
    re.compile(r"^\s*[№N]\s*(\d{1,2})[\s).:\-–—]?", re.IGNORECASE),
    re.compile(r"^\s*(?:Задани[ея]|Задача|Номер)\s*[№]?\s*(\d{1,2})\b", re.IGNORECASE),
    re.compile(r"^\s*(\d{1,2})\s*[).]\s+(?=\S)"),
]


def detect_file_type(head: bytes, file_name: Optional[str] = None) -> str:
    """Определяем тип по магическим байтам; расширение — только fallback."""
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return "docx"
    if head.startswith(b"\xff\xd8"):
        return "image_jpg"
    if head.startswith(b"\x89PNG"):
        return "image_png"
    ext = (file_name or "").rsplit(".", 1)[-1].lower() if file_name else ""
    if ext in ("jpg", "jpeg", "png", "webp"):
        return f"image_{ext}"
    if ext == "pdf":
        return "pdf"
    if ext == "docx":
        return "docx"
    if ext in ("txt", "md"):
        return "txt"
    return "unknown"


def extract_pdf_pages(file_bytes: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(file_bytes))
    return [(page.extract_text() or "") for page in reader.pages]


def extract_docx_text(file_bytes: bytes) -> str:
    from docx import Document  # локальный импорт: пакет нужен только для docx

    document = Document(io.BytesIO(file_bytes))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:  # бланки ответов часто в таблицах
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def merge_segments(segments: list[OCRSegment]) -> list[OCRSegment]:
    """Склейка фрагментов одной задачи (в т.ч. начатых на разных страницах)."""
    merged: dict[int, OCRSegment] = {}
    order: list[int] = []
    for seg in segments:
        if seg.task_number is None:
            continue
        num = seg.task_number
        if num not in merged:
            merged[num] = seg.model_copy()
            order.append(num)
        else:
            main = merged[num]
            main.text += "\n" + seg.text
            main.confidence = min(main.confidence, seg.confidence)
            if seg.page != main.page:
                main.was_split_across_pages = True
                main.page = max(main.page, seg.page)
    return [merged[n] for n in order]


def parse_segments_from_text(full_text: str) -> tuple[list[OCRSegment], list[OCRSegment]]:
    """Детерминированная привязка строк текста к номерам задач.

    Returns:
        (segments, unmatched): unmatched — шапка работы до первого маркера задачи.
    """
    segments: list[OCRSegment] = []
    preamble: list[str] = []
    current_num: Optional[int] = None
    current_lines: list[str] = []

    def flush() -> None:
        text = "\n".join(current_lines).strip()
        if not text:
            return
        seg = OCRSegment(
            task_number=current_num,
            text=text,
            confidence=1.0 if current_num is not None else 0.4,
        )
        if current_num is None:
            preamble.append(text)
        else:
            segments.append(seg)

    for line in full_text.splitlines():
        num: Optional[int] = None
        remainder = line
        for pattern in _TASK_LINE_PATTERNS:
            m = pattern.match(line)
            if m:
                num = int(m.group(1))
                remainder = line[m.end():]
                break
        if num is not None:
            flush()
            current_num, current_lines = num, [remainder]
        else:
            current_lines.append(line)
    flush()

    segments = merge_segments(segments)
    unmatched = [OCRSegment(task_number=None, text="\n".join(preamble), confidence=0.4)] if preamble else []
    return segments, unmatched


def build_vision_content(data_uri: str, mime: str) -> list[dict]:
    """Content-блоки для Chat Completions: картинка или PDF (base64 data URI)."""
    content: list[dict] = [
        {"type": "text", "text": "Транскрибируй работу ученика строго по правилам."}
    ]
    if mime == "application/pdf":
        content.append({"type": "file", "file": {"filename": "work.pdf", "file_data": data_uri}})
    else:
        content.append({"type": "image_url", "image_url": {"url": data_uri}})
    return content


class ExtractionService:
    """Фасад этапа извлечения: маршрутизация по типу файла + Vision OCR."""

    def __init__(self, llm: LLMClient, settings: Settings) -> None:
        self.llm = llm
        self.s = settings

    def extract(self, *, file_bytes: bytes, file_name: Optional[str]) -> ExtractedSubmission:
        kind = detect_file_type(file_bytes[:8], file_name)

        if kind == "pdf":
            pages = extract_pdf_pages(file_bytes)
            text = "\n".join(pages)
            if len(text.strip()) < self.s.min_extracted_chars:  # скан/рукопись -> OCR
                return self._vision_extract(file_bytes, "application/pdf", fallback_pages=len(pages) or 1)
            segments, unmatched = parse_segments_from_text(text)
            return ExtractedSubmission(
                source_type="pdf_text", full_text=text, segments=segments,
                unmatched_segments=unmatched, pages=len(pages) or 1,
            )

        if kind == "docx":
            text = extract_docx_text(file_bytes)
            segments, unmatched = parse_segments_from_text(text)
            return ExtractedSubmission(
                source_type="docx", full_text=text, segments=segments,
                unmatched_segments=unmatched, pages=1,
            )

        if kind.startswith("image_"):
            ext = kind.split("_", 1)[1]
            mime = IMAGE_MIME.get(ext, "image/jpeg")
            return self._vision_extract(file_bytes, mime, fallback_pages=1)

        if kind == "txt":
            text = file_bytes.decode("utf-8", errors="replace")
            segments, unmatched = parse_segments_from_text(text)
            return ExtractedSubmission(
                source_type="plain_text", full_text=text, segments=segments,
                unmatched_segments=unmatched, pages=1,
            )

        raise ValueError("неподдерживаемый тип файла: ожидается JPG/PNG (изображение), PDF или DOCX")

    def _vision_extract(
        self, file_bytes: bytes, mime: str, *, fallback_pages: int
    ) -> ExtractedSubmission:
        """OCR через Vision-модель: транскрипция -> перепроверка неуверенных -> merge."""
        if not self.s.ocr_is_vision_capable:
            raise RuntimeError(
                "для распознавания изображений/сканов нужна Vision-модель "
                "(LLM_PROVIDER=openai + OPENAI_OCR_MODEL=gpt-4o)"
            )
        import base64

        data_uri = f"data:{mime};base64,{base64.b64encode(file_bytes).decode('ascii')}"
        content = build_vision_content(data_uri, mime)

        data = self.llm.chat(
            system=OCR_SYSTEM_PROMPT,
            user=content,
            schema=OCR_JSON_SCHEMA,
            schema_name="ocr_transcription",
        )
        segments = [OCRSegment.model_validate(item) for item in data.get("segments", [])]
        pages_count = max(int(data.get("pages_count") or fallback_pages), 1)

        # Второй проход для неуверенных фрагментов (анти-галлюцинация транскрипции):
        # замена ВСЕГО списка на исправленный (в промпте просят перепроверить перечисленные).
        low_conf = [s for s in segments if s.confidence < self.s.ocr_confidence_threshold]
        if low_conf:
            verify_text = "\n".join(f"[{s.page}] {s.text}" for s in low_conf)
            verify = self.llm.chat(
                system=OCR_SYSTEM_PROMPT,
                user=content + [
                    {"type": "text",
                     "text": f"Перепроверь только эти фрагменты и верни исправленный JSON:\n{verify_text}"}
                ],
                schema=OCR_JSON_SCHEMA,
                schema_name="ocr_transcription",
            )
            confident = [s for s in segments if s.confidence >= self.s.ocr_confidence_threshold]
            fixed = [OCRSegment.model_validate(i) for i in verify.get("segments", [])]
            segments = confident + fixed

        merged = merge_segments(segments)
        unmatched = [s for s in segments if s.task_number is None]
        return ExtractedSubmission(
            source_type="pdf_ocr" if mime == "application/pdf" else "image_ocr",
            full_text="\n\n".join(s.text for s in merged),
            segments=merged,
            unmatched_segments=unmatched,
            pages=pages_count,
            ocr_model=getattr(self.llm, "model", None),
        )
