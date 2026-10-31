from datetime import datetime, timezone

from english_tutor import db

MAX_TEXT_CHARS = 1000
MAX_THEME_CHARS = 80
MAX_VOICE_SECONDS = 120
DAILY_LLM_LIMIT = 200
MAX_MATERIAL_TEXT_CHARS = 6000
MATERIAL_ANALYSES_PER_DAY = 5


def _today() -> str:
    # Consistent UTC date policy for all daily quotas.
    return datetime.now(timezone.utc).date().isoformat()


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


def check_material_text(text: str) -> str | None:
    if text and len(text) > MAX_MATERIAL_TEXT_CHARS:
        return f"Слишком длинный текст (максимум {MAX_MATERIAL_TEXT_CHARS} символов)."
    return None


def daily_left(conn, student_id) -> int:
    today = _today()
    row = conn.execute(
        "SELECT llm_calls FROM daily_usage WHERE student_id=? AND day=?", (student_id, today)
    ).fetchone()
    used = row["llm_calls"] if row else 0
    return max(0, DAILY_LLM_LIMIT - used)


def try_reserve_llm(conn, student_id) -> bool:
    today = _today()
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT llm_calls FROM daily_usage WHERE student_id=? AND day=?", (student_id, today)
        ).fetchone()
        used = row["llm_calls"] if row else 0
        if used >= DAILY_LLM_LIMIT:
            conn.rollback()
            return False
        conn.execute(
            "INSERT INTO daily_usage (student_id, day, llm_calls) VALUES (?, ?, 1) "
            "ON CONFLICT(student_id, day) DO UPDATE SET llm_calls = llm_calls + 1",
            (student_id, today),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


def register_llm_call(conn, student_id) -> None:
    # Backwards-compatible wrapper; prefer try_reserve_llm for atomic reservation.
    db.bump_usage(conn, student_id)


def can_use_llm(conn, student_id) -> bool:
    return daily_left(conn, student_id) > 0


def material_analyses_left(conn, student_id) -> int:
    today = _today()
    row = conn.execute(
        "SELECT material_calls FROM daily_usage WHERE student_id=? AND day=?", (student_id, today)
    ).fetchone()
    used = row["material_calls"] if row else 0
    return max(0, MATERIAL_ANALYSES_PER_DAY - used)


def try_reserve_material_analysis(conn, student_id) -> bool:
    today = _today()
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT material_calls FROM daily_usage WHERE student_id=? AND day=?", (student_id, today)
        ).fetchone()
        used = row["material_calls"] if row else 0
        if used >= MATERIAL_ANALYSES_PER_DAY:
            conn.rollback()
            return False
        conn.execute(
            "INSERT INTO daily_usage (student_id, day, llm_calls, material_calls) VALUES (?, ?, 0, 1) "
            "ON CONFLICT(student_id, day) DO UPDATE SET material_calls = material_calls + 1",
            (student_id, today),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


def register_material_analysis(conn, student_id) -> None:
    try_reserve_material_analysis(conn, student_id)


def can_analyze_material(conn, student_id) -> bool:
    return material_analyses_left(conn, student_id) > 0
