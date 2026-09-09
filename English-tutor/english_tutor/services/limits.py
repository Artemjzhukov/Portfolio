from datetime import date

from english_tutor import db

MAX_TEXT_CHARS = 1000
MAX_THEME_CHARS = 80
MAX_VOICE_SECONDS = 120
DAILY_LLM_LIMIT = 200


def check_text(text: str) -> str | None:
    if text and len(text) > MAX_TEXT_CHARS:
        return f"Слишком длинное сообщение (максимум {MAX_TEXT_CHARS} символов)."
    return None


def check_theme(text: str) -> str | None:
    if text and len(text) > MAX_THEME_CHARS:
        return f"Слишком длинная тема (максимум {MAX_THEME_CHARS} символов)."
    return None


def check_voice(voice) -> str | None:
    duration = getattr(voice, "duration", 0) or 0
    if duration > MAX_VOICE_SECONDS:
        return f"Голосовое слишком длинное (максимум {MAX_VOICE_SECONDS} секунд)."
    return None


def daily_left(conn, student_id) -> int:
    today = str(date.today())
    row = conn.execute(
        "SELECT llm_calls FROM daily_usage WHERE student_id=? AND day=?",
        (student_id, today),
    ).fetchone()
    used = row["llm_calls"] if row else 0
    return max(0, DAILY_LLM_LIMIT - used)


def register_llm_call(conn, student_id) -> None:
    db.bump_usage(conn, student_id)


def can_use_llm(conn, student_id) -> bool:
    return daily_left(conn, student_id) > 0
