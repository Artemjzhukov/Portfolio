import pytest

from english_tutor import db
from english_tutor.services import stats


@pytest.fixture
def active_student(conn):
    db.upsert_student(conn, 42, status="active", level="B1")
    return 42


def _lesson_with_progress(conn, tg_id, level, topic):
    db.upsert_student(conn, tg_id, status="active", level=level)
    cur = conn.execute(
        "INSERT INTO lessons (kind, level, topic, student_id, content_json) "
        "VALUES ('curriculum', ?, ?, NULL, '{}')",
        (level, topic),
    )
    db.record_progress(conn, tg_id, cur.lastrowid, "completed", 3)
    conn.commit()


def test_overview_empty(active_student, conn):
    o = stats.overview(conn, 42)
    assert o["level"] == "B1" and o["lessons_done"] == 0
    assert o["spine_total"] == 6 and o["cards_total"] == 0
    assert o["retention"] is None and o["corrections"] == 0


def test_overview_with_data(active_student, conn):
    _lesson_with_progress(conn, 42, "B1", "Present Perfect vs Past Simple")
    srs = pytest.importorskip("english_tutor.services.srs")
    srs.ensure_card(conn, 42, "cat", "кошка")
    card = conn.execute("SELECT * FROM srs_cards").fetchone()
    db.log_review(conn, 42, card["id"], True)
    db.insert_correction(conn, 42, "I goed", "I went", "irregular verb", source="chat")
    o = stats.overview(conn, 42)
    assert o["lessons_done"] == 1 and o["spine_done"] == 1
    assert o["cards_total"] == 1 and o["retention"] == 100
    assert o["corrections"] == 1


def test_spine_completed_topics_dedup(active_student, conn):
    cur = conn.execute(
        "INSERT INTO lessons (kind, level, topic, student_id, content_json) "
        "VALUES ('curriculum', 'B1', 'Present Perfect vs Past Simple', NULL, '{}')"
    )
    db.record_progress(conn, 42, cur.lastrowid, "completed", 3)
    with pytest.raises(Exception):
        conn.execute(
            "INSERT INTO lessons (kind, level, topic, student_id, content_json) "
            "VALUES ('curriculum', 'B1', 'Present Perfect vs Past Simple', NULL, '{}')"
        )
    assert stats.spine_completed_topics(conn, 42, "B1") == ["Present Perfect vs Past Simple"]


def test_error_patterns_frequency(active_student, conn):
    for _ in range(3):
        db.insert_correction(conn, 42, "I goed", "I went", "verb", source="chat")
    db.insert_correction(conn, 42, "a apple", "an apple", "article", source="chat")
    patterns = stats.error_patterns(conn, 42)
    assert patterns[0]["n"] == 3 and patterns[0]["wrong"] == "I goed"


async def test_categorize_patterns_llm_cached(active_student, conn):
    db.insert_correction(conn, 42, "I goed", "I went", "verb", source="chat")
    calls = []

    class LLM:
        async def chat_json_async(self, system, user):
            calls.append(user)
            return {"items": [{"id": 1, "category": "tenses"}]}

    counts = await stats.categorize_patterns(conn, 42, LLM())
    assert counts == {"tenses": 1}
    assert calls and "I goed" in calls[0]

    # second call: nothing uncategorized → LLM not called again
    counts2 = await stats.categorize_patterns(conn, 42, LLM())
    assert counts2 == {"tenses": 1}
    assert len(calls) == 1


async def test_categorize_llm_failure_returns_none(active_student, conn):
    db.insert_correction(conn, 42, "I goed", "I went", "verb", source="chat")

    class LLM:
        async def chat_json_async(self, system, user):
            raise RuntimeError("boom")

    assert await stats.categorize_patterns(conn, 42, LLM()) is None


def test_format_categories_russian():
    text = stats.format_categories({"articles": 5, "tenses": 3})
    assert "артикли (5)" in text and "времена (3)" in text
    assert stats.format_categories({}) is None


def test_weekly_window(active_student, conn):
    _lesson_with_progress(conn, 42, "B1", "Present Perfect vs Past Simple")
    db.insert_correction(conn, 42, "x", "y", "z", source="chat")
    srs = pytest.importorskip("english_tutor.services.srs")
    srs.ensure_card(conn, 42, "cat", "кошка")
    card = conn.execute("SELECT * FROM srs_cards").fetchone()
    db.log_review(conn, 42, card["id"], True)
    w = stats.weekly(conn, 42)
    assert w["lessons"] == 1 and w["corrections"] == 1 and w["reviews"] == 1


def test_format_weekly_lines(active_student, conn):
    line = stats.format_weekly_lines(conn)
    assert line and "42" in line and "B1" in line
