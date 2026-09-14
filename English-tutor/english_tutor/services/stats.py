from datetime import date, timedelta

from english_tutor import db
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
