"""LLM grammar feedback for spoken English answers (Stage 4G.2).

The service analyses the Whisper transcript with the LLM, using the Pattern Bank
as context, and returns a structured result the handlers can render.

Design constraints (approved scope):
- LLM analysis only; there is no rule-based fallback.
- Failures never block task completion: the caller keeps the transcript and the
  existing lesson flow continues unchanged.
- No new database tables and no schema changes (persisting mistakes is 4G.3).
- The service never claims an answer is correct unless the LLM analysed it.
"""

from __future__ import annotations

import asyncio
import logging

from english_tutor.services.patterns import (
    build_patterns_prompt,
    normalize_pattern_id,
)

logger = logging.getLogger(__name__)

STATUS_ANALYZED = "analyzed"
STATUS_LLM_ERROR = "llm_error"
STATUS_INSUFFICIENT_CONTEXT = "insufficient_context"
STATUS_UNAVAILABLE = "unavailable"

MIN_TRANSCRIPT_WORDS = 3
MAX_CORRECTIONS = 5

UNAVAILABLE_MESSAGE = "Разбор грамматики сейчас недоступен. Расшифровка сохранена."
TOO_SHORT_MESSAGE = "Ответ слишком короткий для разбора — скажи хотя бы одно полное предложение."
EMPTY_MESSAGE = "Не удалось разобрать речь — попробуй записать ответ ещё раз."

SYSTEM_PROMPT = (
    "You are an experienced English teacher for Russian-speaking IT professionals. "
    "You check a spoken answer that was transcribed by speech recognition.\n\n"
    "Rules:\n"
    "1. Correct only real grammar mistakes. Ignore punctuation, capitalisation and "
    "obvious speech-recognition noise.\n"
    "2. Never invent mistakes. If the answer is grammatically correct, return an "
    "empty corrections list.\n"
    "3. Keep the learner's meaning and change as little as possible.\n"
    "4. Explain every correction briefly in Russian.\n"
    "5. Use a pattern_id from the list you are given, or null if the mistake does "
    "not match a listed pattern. Never invent pattern IDs.\n"
    "6. If the transcript is too short or unreadable, set status to "
    '"insufficient_context".\n'
    "7. Reply with exactly one JSON object, no markdown, no commentary.\n\n"
    "JSON schema:\n"
    '{"status": "analyzed" | "insufficient_context",\n'
    ' "overall_message": "краткий итог по-русски",\n'
    ' "corrections": [{"original": "...", "corrected": "...",\n'
    '   "explanation_ru": "...", "pattern_id": "pat_002" | null,\n'
    '   "confidence": 0.0}],\n'
    ' "correct_patterns": ["pat_002"],\n'
    ' "natural_version": "более естественный вариант или null",\n'
    ' "naturalness_note_ru": "замечание о стиле или null"}'
)


def _result(status: str, message: str, transcript: str) -> dict:
    """Build an empty analysis result with the fixed public shape."""
    return {
        "status": status,
        "overall_message": message,
        "corrections": [],
        "correct_patterns": [],
        "natural_version": None,
        "naturalness_note_ru": None,
        "transcript": transcript,
    }


def _clean_text(value) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _clean_confidence(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0.0, min(1.0, float(value)))


def _clean_corrections(raw) -> list[dict]:
    """Keep only well-formed corrections; drop anything the LLM mangled."""
    if not isinstance(raw, list):
        return []
    cleaned: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        original = _clean_text(item.get("original"))
        corrected = _clean_text(item.get("corrected"))
        if not original or not corrected or original == corrected:
            continue
        pattern_id = normalize_pattern_id(item.get("pattern_id"))
        cleaned.append(
            {
                "original": original,
                "corrected": corrected,
                "explanation_ru": _clean_text(item.get("explanation_ru")),
                "pattern_id": str(pattern_id) if pattern_id else None,
                "confidence": _clean_confidence(item.get("confidence")),
            }
        )
        if len(cleaned) >= MAX_CORRECTIONS:
            break
    return cleaned


def _clean_pattern_ids(raw) -> list[str]:
    if not isinstance(raw, list):
        return []
    result: list[str] = []
    for item in raw:
        pattern_id = normalize_pattern_id(item)
        if pattern_id is None:
            continue
        value = str(pattern_id)
        if value not in result:
            result.append(value)
    return result


def _build_user_prompt(
    transcript: str,
    task_description: str | None,
    student_level: str | None,
    pattern_ids,
) -> str:
    blocks = [f"Answer transcript: {transcript}"]
    if task_description:
        blocks.append(f"Task the learner was answering: {task_description}")
    if student_level:
        blocks.append(f"Learner CEFR level: {student_level}")
    patterns_block = build_patterns_prompt(pattern_ids or [], student_level)
    if patterns_block:
        blocks.append("Grammar patterns in focus for this lesson:\n" + patterns_block)
    blocks.append("Analyse the answer now and return the JSON object.")
    return "\n\n".join(blocks)


async def _ask_llm(llm, system: str, user: str) -> dict:
    if hasattr(llm, "chat_json_async"):
        return await llm.chat_json_async(system, user)
    return await asyncio.to_thread(llm.chat_json, system, user)


async def analyze_grammar(
    transcript: str,
    llm,
    *,
    task_description: str | None = None,
    student_level: str | None = None,
    pattern_ids=None,
) -> dict:
    """Analyse a transcribed spoken answer with the LLM.

    Returns a dict with the keys ``status``, ``overall_message``, ``corrections``,
    ``correct_patterns``, ``natural_version``, ``naturalness_note_ru`` and
    ``transcript``. ``status`` is one of ``analyzed``, ``llm_error``,
    ``insufficient_context`` or ``unavailable``.

    This function never raises for LLM problems: any failure is reported through
    the ``status`` field so the caller can keep the existing flow.
    """
    text = (transcript or "").strip()
    if not text:
        return _result(STATUS_INSUFFICIENT_CONTEXT, EMPTY_MESSAGE, transcript)

    if len(text.split()) < MIN_TRANSCRIPT_WORDS:
        return _result(STATUS_INSUFFICIENT_CONTEXT, TOO_SHORT_MESSAGE, transcript)

    if llm is None or not (hasattr(llm, "chat_json") or hasattr(llm, "chat_json_async")):
        logger.info("Grammar feedback skipped: LLM service is unavailable")
        return _result(STATUS_UNAVAILABLE, UNAVAILABLE_MESSAGE, transcript)

    user_prompt = _build_user_prompt(text, task_description, student_level, pattern_ids)
    try:
        payload = await _ask_llm(llm, SYSTEM_PROMPT, user_prompt)
    except Exception:
        logger.warning("Grammar feedback LLM call failed", exc_info=True)
        return _result(STATUS_LLM_ERROR, UNAVAILABLE_MESSAGE, transcript)

    if not isinstance(payload, dict):
        logger.warning("Grammar feedback: LLM returned %s instead of an object", type(payload))
        return _result(STATUS_LLM_ERROR, UNAVAILABLE_MESSAGE, transcript)

    status = payload.get("status")
    if status == STATUS_INSUFFICIENT_CONTEXT:
        message = _clean_text(payload.get("overall_message")) or TOO_SHORT_MESSAGE
        return _result(STATUS_INSUFFICIENT_CONTEXT, message, transcript)
    if status == STATUS_UNAVAILABLE:
        return _result(STATUS_UNAVAILABLE, UNAVAILABLE_MESSAGE, transcript)
    if status not in (None, STATUS_ANALYZED):
        # Unknown status: never guess that the answer was correct.
        logger.warning("Grammar feedback: unexpected LLM status %r", status)
        return _result(STATUS_LLM_ERROR, UNAVAILABLE_MESSAGE, transcript)

    corrections = _clean_corrections(payload.get("corrections"))
    natural_version = _clean_text(payload.get("natural_version"))
    if natural_version and natural_version.lower() == text.lower():
        natural_version = None
    message = _clean_text(payload.get("overall_message"))
    if not message:
        message = (
            "Грамматических ошибок не нашёл 👍"
            if not corrections
            else f"Нашёл {len(corrections)} ошибок — смотри ниже."
        )

    return {
        "status": STATUS_ANALYZED,
        "overall_message": message,
        "corrections": corrections,
        "correct_patterns": _clean_pattern_ids(payload.get("correct_patterns")),
        "natural_version": natural_version,
        "naturalness_note_ru": _clean_text(payload.get("naturalness_note_ru")),
        "transcript": transcript,
    }


def format_feedback(feedback: dict | None) -> str | None:
    """Render an analysis result as a Telegram-ready Russian message."""
    if not feedback:
        return None
    status = feedback.get("status")

    if status == STATUS_ANALYZED:
        lines = ["🧠 Грамматический разбор:"]
        corrections = feedback.get("corrections") or []
        for correction in corrections:
            line = f"• «{correction['original']}» → «{correction['corrected']}»"
            if correction.get("explanation_ru"):
                line += f" — {correction['explanation_ru']}"
            lines.append(line)
        overall = feedback.get("overall_message")
        if overall:
            lines.append(overall)
        natural_version = feedback.get("natural_version")
        if natural_version:
            lines.append(f"💬 Естественнее: {natural_version}")
        note = feedback.get("naturalness_note_ru")
        if note:
            lines.append(f"ℹ️ {note}")
        return "\n".join(lines)

    if status == STATUS_INSUFFICIENT_CONTEXT:
        return feedback.get("overall_message") or TOO_SHORT_MESSAGE

    if status in (STATUS_LLM_ERROR, STATUS_UNAVAILABLE):
        return "⚠️ " + UNAVAILABLE_MESSAGE

    return None


__all__ = [
    "MIN_TRANSCRIPT_WORDS",
    "STATUS_ANALYZED",
    "STATUS_INSUFFICIENT_CONTEXT",
    "STATUS_LLM_ERROR",
    "STATUS_UNAVAILABLE",
    "analyze_grammar",
    "format_feedback",
]
