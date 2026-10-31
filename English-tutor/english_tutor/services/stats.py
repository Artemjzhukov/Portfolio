from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from english_tutor import db
from english_tutor.config import load_config
from english_tutor.services import spine

CATEGORIES_RU = {
    "tenses": "времена",
    "articles": "артикли",
    "prepositions": "предлоги",
    "word_forms": "формы слов",
    "word_choice": "выбор слова",
    "spelling": "орфография",
    "other": "другое",
}

CATEGORIZE_PROMPT = (
    "Classify each English learner mistake into ONE category from this list: "
    "tenses, articles, prepositions, word_forms, word_choice, spelling, other. "
    'Reply ONLY with JSON: {"items": [{"id": int, "category": str}]}'
)


def spine_completed_topics(conn, tg_id, level) -> list[str]:
    if not level:
        return []
    rows = conn.execute(
        "SELECT DISTINCT l.topic FROM lesson_progress p JOIN lessons l ON p.lesson_id=l.id "
        "WHERE p.student_id=? AND p.status='completed' AND l.level=? AND l.kind='curriculum'",
        (tg_id, level),
    ).fetchall()
    return [r["topic"] for r in rows]


def overview(conn, tg_id) -> dict:
    student = conn.execute("SELECT level FROM students WHERE tg_id=?", (tg_id,)).fetchone()
    level = student["level"] if student else None
    lessons_done = conn.execute(
        "SELECT COUNT(*) c FROM lesson_progress WHERE student_id=? AND status='completed'",
        (tg_id,),
    ).fetchone()["c"]
    done = spine_completed_topics(conn, tg_id, level)
    cards_total = conn.execute(
        "SELECT COUNT(*) c FROM srs_cards WHERE student_id=?", (tg_id,)
    ).fetchone()["c"]
    cards_due = conn.execute(
        "SELECT COUNT(*) c FROM srs_cards WHERE student_id=? AND due_date<=?",
        (tg_id, str(date.today())),
    ).fetchone()["c"]
    answered = conn.execute(
        "SELECT COUNT(*) c FROM srs_reviews WHERE student_id=?", (tg_id,)
    ).fetchone()["c"]
    correct = conn.execute(
        "SELECT COUNT(*) c FROM srs_reviews WHERE student_id=? AND correct=1", (tg_id,)
    ).fetchone()["c"]
    corrections = conn.execute(
        "SELECT COUNT(*) c FROM corrections WHERE student_id=?", (tg_id,)
    ).fetchone()["c"]
    return dict(
        level=level,
        lessons_done=lessons_done,
        spine_done=len(done),
        spine_total=len(spine.topics(level)) if level else 6,
        cards_total=cards_total,
        cards_due=cards_due,
        retention=round(100 * correct / answered) if answered else None,
        corrections=corrections,
    )


def _tz():
    """Return the configured timezone, defaulting to UTC.

    Tries to read ``TZ`` from environment (via load_env pattern); falls back
    to UTC if configuration is unavailable.
    """
    try:
        return ZoneInfo(load_config().tz)
    except Exception:
        # Fallback: try raw env var
        import os
        try:
            return ZoneInfo(os.environ.get("TZ", "Europe/Kiev"))
        except Exception:
            return ZoneInfo("UTC")


def days_ago(value: str | None) -> int | None:
    """Calendar-day difference between ``value`` (datetime or date string) and now.

    Naive datetime strings are interpreted in ``config.tz`` (the learner's local
    timezone).  The current time is also taken in ``config.tz`` so the comparison
    is consistent.

    Returns ``None`` when *value* is ``None`` or unparseable.
    """
    if value is None:
        return None
    tz = _tz()
    try:
        # Try datetime format first (SQLite datetime('now') strings, or ISO with 'T')
        dt = datetime.fromisoformat(value.replace("T", " "))
        if dt.tzinfo is None:
            # SQLite datetime('now') returns naive UTC strings.
            # Interpret as UTC and convert to config.tz.
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        started_day = dt.astimezone(tz).date()
        now_day = datetime.now(tz).date()
        return (now_day - started_day).days
    except (ValueError, TypeError):
        pass
    try:
        # Try date-only format (e.g. srs_reviews.day)
        d = date.fromisoformat(value)
        today = datetime.now(tz).date()
        return (today - d).days
    except (ValueError, TypeError):
        return None


def error_patterns(conn, tg_id, limit: int = 5):
    return conn.execute(
        "SELECT wrong, right, COUNT(*) n FROM corrections WHERE student_id=? "
        "GROUP BY wrong, right ORDER BY n DESC LIMIT ?",
        (tg_id, limit),
    ).fetchall()


async def categorize_patterns(conn, tg_id, llm) -> dict | None:
    """LLM-classify uncategorized corrections (cached in the category column)."""
    rows = conn.execute(
        "SELECT id, wrong FROM corrections WHERE student_id=? AND category IS NULL LIMIT 20",
        (tg_id,),
    ).fetchall()
    if rows:
        listing = "\n".join(f"{r['id']}. {r['wrong']}" for r in rows)
        try:
            data = await llm.chat_json_async(CATEGORIZE_PROMPT, listing)
        except Exception:
            return None
        for item in data.get("items", []):
            if item.get("category") in CATEGORIES_RU and isinstance(item.get("id"), int):
                conn.execute(
                    "UPDATE corrections SET category=? WHERE id=?",
                    (item["category"], item["id"]),
                )
            conn.commit()
    counts = conn.execute(
        "SELECT category, COUNT(*) n FROM corrections WHERE student_id=? "
        "GROUP BY category ORDER BY n DESC",
        (tg_id,),
    ).fetchall()
    return {(r["category"] or "other"): r["n"] for r in counts}


def format_categories(counts: dict, limit: int = 3) -> str | None:
    if not counts:
        return None
    parts = [f"{CATEGORIES_RU.get(k, k)} ({n})" for k, n in counts.items()][:limit]
    return "Слабые места: " + ", ".join(parts)


def weekly(conn, tg_id, days: int = 7) -> dict:
    since = str(date.today() - timedelta(days=days - 1))
    lessons = conn.execute(
        "SELECT COUNT(*) c FROM lesson_progress WHERE student_id=? AND status='completed' "
        "AND completed_at>=?",
        (tg_id, since),
    ).fetchone()["c"]
    corrections = conn.execute(
        "SELECT COUNT(*) c FROM corrections WHERE student_id=? AND created_at>=?",
        (tg_id, since),
    ).fetchone()["c"]
    reviews = conn.execute(
        "SELECT COUNT(*) c FROM srs_reviews WHERE student_id=? AND day>=?", (tg_id, since)
    ).fetchone()["c"]
    llm = conn.execute(
        "SELECT COALESCE(SUM(llm_calls), 0) c FROM daily_usage WHERE student_id=? AND day>=?",
        (tg_id, since),
    ).fetchone()["c"]
    return dict(lessons=lessons, corrections=corrections, reviews=reviews, llm=llm)


def format_weekly_lines(conn, days: int = 7) -> str | None:
    lines = []
    for s in db.list_students(conn, "active"):
        w = weekly(conn, s["tg_id"], days)
        lines.append(
            f"• {s['name'] or s['tg_id']} ({s['level'] or '—'}): уроков {w['lessons']}, "
            f"исправлений {w['corrections']}, повторений {w['reviews']}"
        )
    return "\n".join(lines) if lines else None


# ---------------------------------------------------------------------------
# Option 3: Last-Activity Summary
# ---------------------------------------------------------------------------

def last_activity(conn, tg_id) -> dict:
    """Return the learner's most recent activity timestamps across all content types.

    All data is derived from existing tables — no extra schema is needed.
    A non-None ``last_story_started_at`` with a topic means the story is
    in-progress (stale if it started several days ago).
    """
    student = conn.execute(
        "SELECT level FROM students WHERE tg_id=?", (tg_id,)
    ).fetchone()
    level = student["level"] if student else None

    last_lesson = conn.execute(
        "SELECT completed_at FROM lesson_progress "
        "WHERE student_id=? AND status='completed' ORDER BY completed_at DESC LIMIT 1",
        (tg_id,),
    ).fetchone()

    last_story = conn.execute(
        "SELECT completed_at FROM story_progress "
        "WHERE student_id=? ORDER BY completed_at DESC LIMIT 1",
        (tg_id,),
    ).fetchone()

    stale_story = conn.execute(
        "SELECT s.topic, a.created_at FROM active_story_sessions a "
        "JOIN stories s ON a.story_id = s.id "
        "WHERE a.student_id=? ORDER BY a.created_at DESC LIMIT 1",
        (tg_id,),
    ).fetchone()

    last_corr = conn.execute(
        "SELECT created_at FROM corrections "
        "WHERE student_id=? ORDER BY created_at DESC LIMIT 1",
        (tg_id,),
    ).fetchone()

    last_review = conn.execute(
        "SELECT day FROM srs_reviews "
        "WHERE student_id=? ORDER BY day DESC LIMIT 1",
        (tg_id,),
    ).fetchone()

    return dict(
        level=level,
        last_lesson_completed=last_lesson["completed_at"] if last_lesson else None,
        last_story_completed=last_story["completed_at"] if last_story else None,
        last_story_topic=stale_story["topic"] if stale_story else None,
        last_story_started_at=stale_story["created_at"] if stale_story else None,
        last_correction=last_corr["created_at"] if last_corr else None,
        last_srs_review=last_review["day"] if last_review else None,
    )


def format_activity_nudge(activity: dict) -> str:
    """Build a contextual nudge suffix for reminders based on last activity.

    Thresholds are computed in **calendar days** using ``config.tz``:

    * Stale active story session started 1–14 days ago → ``/resume``
    * Lesson completed ≤ 7 days ago → ``/lessons``
    * Story completed ≤ 7 days ago → ``/story``
    * SRS review performed ≤ 7 days ago → ``/review``
    * Otherwise → generic ``/lessons`` fallback

    Priority follows the order above.
    """
    STALE_STORY_MIN_DAYS = 1
    STALE_STORY_MAX_DAYS = 14
    RECENT_MAX_DAYS = 7

    if activity.get("last_story_started_at"):
        started_days = days_ago(activity["last_story_started_at"])
        if started_days is not None and STALE_STORY_MIN_DAYS <= started_days <= STALE_STORY_MAX_DAYS:
            topic = activity.get("last_story_topic", "")
            return (
                f"📖 Ты начал рассказ «{topic}» "
                f"{started_days} дней назад — заверши его!\nПродолжить: /resume"
            )

    lesson_days = days_ago(activity.get("last_lesson_completed"))
    if lesson_days is not None and lesson_days <= RECENT_MAX_DAYS:
        return "📚 Продолжи серию уроков: /lessons"

    story_days = days_ago(activity.get("last_story_completed"))
    if story_days is not None and story_days <= RECENT_MAX_DAYS:
        return "📖 Хочешь новый рассказ? /story"

    review_days = days_ago(activity.get("last_srs_review"))
    if review_days is not None and review_days <= RECENT_MAX_DAYS:
        return "🔁 Слова к повторению ждут: /review"

    return "🎯 Начни с урока: /lessons"
