from datetime import datetime, timedelta

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


# ---------------------------------------------------------------------------
# Option 3: Last-Activity Summary
# ---------------------------------------------------------------------------

def test_last_activity_empty(active_student, conn):
    """No activity at all → all fields None."""
    a = stats.last_activity(conn, 42)
    assert a["level"] == "B1"
    assert a["last_lesson_completed"] is None
    assert a["last_story_completed"] is None
    assert a["last_story_topic"] is None
    assert a["last_story_started_at"] is None
    assert a["last_correction"] is None
    assert a["last_srs_review"] is None


def test_last_activity_with_completed_story(active_student, conn):
    """A completed story is surfaced via story_progress.completed_at."""
    db.upsert_student(conn, 42, status="active", level="A2")
    conn.execute(
        "INSERT INTO stories (student_id, level, topic, content_json) "
        "VALUES (42, 'A2', 'food', '{}')",
    )
    conn.commit()
    story_id = conn.execute("SELECT id FROM stories WHERE student_id=42").fetchone()["id"]
    conn.execute(
        "INSERT INTO story_progress (student_id, story_id, questions_score, "
        "retell_transcript, retell_passed) "
        "VALUES (42, ?, 2, 'transcript', 1)",
        (story_id,),
    )
    conn.commit()
    a = stats.last_activity(conn, 42)
    assert a["last_story_completed"] is not None
    assert a["last_story_topic"] is None  # story completed → no stale session
    assert a["last_story_started_at"] is None


def test_last_activity_stale_story_detected(active_student, conn):
    """An active_story_sessions row means the story is in-progress (stale if days old)."""
    db.upsert_student(conn, 42, status="active", level="A2")
    conn.execute(
        "INSERT INTO stories (student_id, level, topic, content_json) "
        "VALUES (42, 'A2', 'run out of', '{}')",
    )
    conn.commit()
    story_id = conn.execute("SELECT id FROM stories WHERE student_id=42").fetchone()["id"]
    conn.execute(
        "INSERT INTO active_story_sessions "
        "(student_id, story_id, stage, q_idx, correct) VALUES (42, ?, 'answering_questions', 1, 0)",
        (story_id,),
    )
    conn.commit()
    a = stats.last_activity(conn, 42)
    assert a["last_story_started_at"] is not None
    assert a["last_story_topic"] == "run out of"


def test_last_activity_with_corrections(active_student, conn):
    """Corrections are reflected in last_correction."""
    db.insert_correction(conn, 42, "I goed", "I went", "past tense", source="chat")
    a = stats.last_activity(conn, 42)
    assert a["last_correction"] is not None


def test_last_activity_with_srs_review(active_student, conn):
    """SRS review day is reflected in last_srs_review."""
    from english_tutor.services import srs as srs_svc
    srs_svc.ensure_card(conn, 42, "cat", "кошка")
    card = conn.execute("SELECT * FROM srs_cards WHERE student_id=42").fetchone()
    db.log_review(conn, 42, card["id"], True)
    a = stats.last_activity(conn, 42)
    assert a["last_srs_review"] is not None


def test_last_activity_with_completed_lesson(active_student, conn):
    """Completed lessons are reflected in last_lesson_completed."""
    _lesson_with_progress(conn, 42, "B1", "Past Simple")
    a = stats.last_activity(conn, 42)
    assert a["last_lesson_completed"] is not None


def test_format_nudge_stale_story_priority():
    """Stale story session → nudge mentions /resume."""
    from unittest.mock import patch

    fixed_now = datetime(2026, 6, 10, 12, 0, 0)
    started = datetime(2026, 6, 5, 12, 0, 0)
    activity = dict(
        level="A2",
        last_story_completed=None,
        last_story_topic="run out of",
        last_story_started_at=_fmt(started),
        last_lesson_completed=None,
        last_correction=None,
        last_srs_review=None,
    )
    with patch("english_tutor.services.stats.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.fromisoformat.side_effect = lambda v: datetime.fromisoformat(v)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        nudge = stats.format_activity_nudge(activity)
    assert "/resume" in nudge
    assert "run out of" in nudge  # the topic


def test_format_nudge_recent_lesson_no_stale_story():
    """Recent lesson completed, no stale story → suggest /lessons."""
    activity = dict(
        level="A2",
        last_story_completed="2026-09-28 12:00:00",
        last_story_topic=None,
        last_story_started_at=None,
        last_lesson_completed="2026-09-28 12:00:00",
        last_correction="2026-09-27 10:00:00",
        last_srs_review="2026-09-28",
    )
    nudge = stats.format_activity_nudge(activity)
    assert "/lessons" in nudge


def test_format_nudge_no_activity_fallback():
    """No activity at all → generic suggestion."""
    activity = dict(
        level="A2",
        last_story_completed=None,
        last_story_topic=None,
        last_story_started_at=None,
        last_lesson_completed=None,
        last_correction=None,
        last_srs_review=None,
    )
    nudge = stats.format_activity_nudge(activity)
    assert "/lessons" in nudge  # generic fallback


# ---------------------------------------------------------------------------
# Calendar-day-based thresholds for nudges (fixed-time tests)
# ---------------------------------------------------------------------------


def _fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _fixed_story_activity(started_at_str, topic="run out of"):
    return dict(
        level="A2",
        last_story_completed=None,
        last_story_topic=topic,
        last_story_started_at=started_at_str,
        last_lesson_completed=None,
        last_correction=None,
        last_srs_review=None,
    )


def test_stale_story_one_day_old_uses_resume():
    """Active story session 1 day old → /resume nudge."""
    from unittest.mock import patch

    fixed_now = datetime(2026, 6, 10, 12, 0, 0)
    started = datetime(2026, 6, 9, 12, 0, 0)
    activity = _fixed_story_activity(_fmt(started))
    with patch("english_tutor.services.stats.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.fromisoformat.side_effect = lambda v: datetime.fromisoformat(v)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        nudge = stats.format_activity_nudge(activity)
    assert "/resume" in nudge
    assert "1 дней" in nudge or "1 дня" in nudge


def test_stale_story_seven_days_old_uses_resume():
    """Active story session 7 days old → /resume nudge."""
    from unittest.mock import patch

    fixed_now = datetime(2026, 6, 10, 12, 0, 0)
    started = datetime(2026, 6, 3, 12, 0, 0)
    activity = _fixed_story_activity(_fmt(started))
    with patch("english_tutor.services.stats.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.fromisoformat.side_effect = lambda v: datetime.fromisoformat(v)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        nudge = stats.format_activity_nudge(activity)
    assert "/resume" in nudge


def test_stale_story_fourteen_days_old_uses_resume():
    """Active story session 14 days old → /resume nudge."""
    from unittest.mock import patch

    fixed_now = datetime(2026, 6, 10, 12, 0, 0)
    started = datetime(2026, 5, 27, 12, 0, 0)
    activity = _fixed_story_activity(_fmt(started))
    with patch("english_tutor.services.stats.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.fromisoformat.side_effect = lambda v: datetime.fromisoformat(v)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        nudge = stats.format_activity_nudge(activity)
    assert "/resume" in nudge


def test_stale_story_fifteen_days_old_uses_fallback():
    """Active story session 15 days old → fallback (not /resume)."""
    from unittest.mock import patch

    fixed_now = datetime(2026, 6, 10, 12, 0, 0)
    started = datetime(2026, 5, 26, 12, 0, 0)
    activity = _fixed_story_activity(_fmt(started))
    with patch("english_tutor.services.stats.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.fromisoformat.side_effect = lambda v: datetime.fromisoformat(v)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        nudge = stats.format_activity_nudge(activity)
        nudge = stats.format_activity_nudge(activity)
    assert "/lessons" in nudge


def test_stale_story_crosses_midnight_uses_resume():
    """Story started late evening Kyiv yesterday (= UTC evening yesterday) → /resume.

    SQLite datetime('now') stores UTC. 'now' at Kyiv 2026-06-10 00:30
    = UTC 2026-06-09 21:30. Started at Kyiv 2026-06-09 22:30 = UTC 2026-06-09 19:30.
    Calendar day in Kyiv: started = 2026-06-09, now = 2026-06-10 → 1 day.
    """
    from unittest.mock import patch
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Europe/Kiev")
    # 'now' in Kyiv 2026-06-10 00:30 = UTC 2026-06-09 21:30
    fixed_now = datetime(2026, 6, 10, 0, 30, 0, tzinfo=tz)
    # Started at Kyiv 2026-06-09 22:30 = UTC 2026-06-09 19:30
    # Stored as naive UTC: "2026-06-09 19:30:00"
    started_str = "2026-06-09 19:30:00"
    activity = _fixed_story_activity(started_str)
    with patch("english_tutor.services.stats.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.fromisoformat.side_effect = lambda v: datetime.fromisoformat(v)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        nudge = stats.format_activity_nudge(activity)
    # Calendar day difference = 1 day in Kyiv
    assert "/resume" in nudge


def test_active_story_session_uses_session_created_at_not_story_created_at(conn):
    """last_activity must use active_story_sessions.created_at."""

    student_id = 42
    db.upsert_student(conn, student_id, status="active", level="A2")

    story_created_str = "2026-04-01 10:00:00"
    conn.execute(
        "INSERT INTO stories (student_id, level, topic, content_json, created_at) "
        "VALUES (?, 'A2', 'run out of', '{}', ?)",
        (student_id, story_created_str),
    )
    conn.commit()
    story_id = conn.execute(
        "SELECT id FROM stories WHERE student_id=?", (student_id,)
    ).fetchone()["id"]

    session_created_str = (
        (datetime.now() - timedelta(days=1))
        .replace(microsecond=0)
        .strftime("%Y-%m-%d %H:%M:%S")
    )
    conn.execute(
        "INSERT INTO active_story_sessions "
        "(student_id, story_id, stage, q_idx, correct, created_at, updated_at) "
        "VALUES (?, ?, 'answering_questions', 1, 0, ?, ?)",
        (student_id, story_id, session_created_str, session_created_str),
    )
    conn.commit()

    a = stats.last_activity(conn, student_id)
    assert a["last_story_started_at"] == session_created_str
    assert a["last_story_started_at"] != story_created_str


def test_completed_lesson_eight_days_old_uses_fallback():
    """Lesson completed 8 days ago → fallback (not /lessons nudge)."""
    from unittest.mock import patch

    fixed_now = datetime(2026, 6, 10, 12, 0, 0)
    completed = datetime(2026, 6, 2, 12, 0, 0)
    activity = dict(
        level="B1",
        last_story_completed=None,
        last_story_topic=None,
        last_story_started_at=None,
        last_lesson_completed=_fmt(completed),
        last_correction=None,
        last_srs_review=None,
    )
    with patch("english_tutor.services.stats.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.fromisoformat.side_effect = lambda v: datetime.fromisoformat(v)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        nudge = stats.format_activity_nudge(activity)
    assert "/lessons" in nudge  # fallback


def test_completed_story_eight_days_old_uses_fallback():
    """Story completed 8 days ago → fallback (not /story nudge)."""
    from unittest.mock import patch

    fixed_now = datetime(2026, 6, 10, 12, 0, 0)
    completed = datetime(2026, 6, 2, 12, 0, 0)
    activity = dict(
        level="B1",
        last_story_completed=_fmt(completed),
        last_story_topic=None,
        last_story_started_at=None,
        last_lesson_completed=None,
        last_correction=None,
        last_srs_review=None,
    )
    with patch("english_tutor.services.stats.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.fromisoformat.side_effect = lambda v: datetime.fromisoformat(v)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        nudge = stats.format_activity_nudge(activity)
    assert "/story" not in nudge
    assert "/lessons" in nudge


def test_srs_review_ten_days_old_uses_fallback():
    """SRS review 10 days ago → fallback (not /review nudge)."""
    from unittest.mock import patch

    fixed_now = datetime(2026, 6, 10, 12, 0, 0)
    review_day = (datetime(2026, 5, 31, 12, 0, 0)).strftime("%Y-%m-%d")
    activity = dict(
        level="B1",
        last_story_completed=None,
        last_story_topic=None,
        last_story_started_at=None,
        last_lesson_completed=None,
        last_correction=None,
        last_srs_review=review_day,
    )
    with patch("english_tutor.services.stats.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.fromisoformat.side_effect = lambda v: datetime.fromisoformat(v)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        nudge = stats.format_activity_nudge(activity)
    assert "/review" not in nudge
    assert "/lessons" in nudge


def test_no_recent_activity_uses_lessons():
    """All activity >7 days old → fallback to /lessons."""
    from unittest.mock import patch

    fixed_now = datetime(2026, 6, 20, 12, 0, 0)
    activity = dict(
        level="B1",
        last_story_completed=(datetime(2026, 6, 5, 12, 0, 0)).strftime("%Y-%m-%d %H:%M:%S"),
        last_story_topic=None,
        last_story_started_at=None,
        last_lesson_completed=(datetime(2026, 6, 5, 12, 0, 0)).strftime("%Y-%m-%d %H:%M:%S"),
        last_correction=None,
        last_srs_review=(datetime(2026, 6, 5, 12, 0, 0)).strftime("%Y-%m-%d"),
    )
    with patch("english_tutor.services.stats.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.fromisoformat.side_effect = lambda v: datetime.fromisoformat(v)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        nudge = stats.format_activity_nudge(activity)
    assert "/lessons" in nudge


# ---------------------------------------------------------------------------
# days_ago: SQLite datetime('now') is UTC; config.tz is Europe/Kiev
# ---------------------------------------------------------------------------

def test_days_ago_utc_before_midnight_kyiv_is_previous_day():
    """UTC 2026-06-09 20:30 == Kyiv 2026-06-09 23:30 -> 1 calendar day ago at Kyiv 00:30."""
    from unittest.mock import patch
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Europe/Kiev")
    # "now" is Kyiv 2026-06-10 00:30 = UTC 2026-06-09 21:30
    fixed_now = datetime(2026, 6, 10, 0, 30, 0, tzinfo=tz)
    # value stored by SQLite datetime('now') in UTC: "2026-06-09 20:30:00"
    utc_value = "2026-06-09 20:30:00"

    with patch("english_tutor.services.stats.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.fromisoformat.side_effect = lambda v: datetime.fromisoformat(v)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = stats.days_ago(utc_value)

    # UTC 20:30 -> Kyiv 23:30 -> calendar day 2026-06-09
    # now Kyiv 00:30 -> calendar day 2026-06-10
    # diff = 1 day
    assert result == 1


def test_days_ago_utc_after_midnight_kyiv_is_same_day():
    """UTC 2026-06-09 21:30 == Kyiv 2026-06-10 00:30 -> 0 calendar days ago at Kyiv 00:30."""
    from unittest.mock import patch
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Europe/Kiev")
    fixed_now = datetime(2026, 6, 10, 0, 30, 0, tzinfo=tz)
    # UTC 21:30 -> Kyiv 00:30 next day -> same calendar day as now
    utc_value = "2026-06-09 21:30:00"

    with patch("english_tutor.services.stats.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.fromisoformat.side_effect = lambda v: datetime.fromisoformat(v)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = stats.days_ago(utc_value)

    assert result == 0


def test_days_ago_none_input():
    """days_ago(None) -> None."""
    assert stats.days_ago(None) is None


def test_days_ago_date_only_uses_config_tz():
    """srs_reviews.day (date-only) compared against current date in config.tz, not server TZ."""
    from unittest.mock import patch
    from zoneinfo import ZoneInfo

    day_value = "2026-06-10"  # today in Kyiv

    tz = ZoneInfo("Europe/Kyiv")
    with patch("english_tutor.services.stats._tz") as mock_tz:
        mock_tz.return_value = tz
        # Patch datetime.now to return a fixed aware datetime in Kyiv
        with patch("english_tutor.services.stats.datetime") as mock_dt:
            fixed_now = datetime(2026, 6, 10, 0, 30, 0, tzinfo=tz)
            mock_dt.now.return_value = fixed_now
            mock_dt.fromisoformat.side_effect = lambda v: datetime.fromisoformat(v)
            result = stats.days_ago(day_value)

    assert result == 0


def test_days_ago_date_only_yesterday_in_config_tz():
    """srs_reviews.day = yesterday in config.tz -> 1 day ago."""
    from unittest.mock import patch
    from zoneinfo import ZoneInfo

    day_value = "2026-06-09"

    tz = ZoneInfo("Europe/Kyiv")
    with patch("english_tutor.services.stats._tz") as mock_tz:
        mock_tz.return_value = tz
        with patch("english_tutor.services.stats.datetime") as mock_dt:
            fixed_now = datetime(2026, 6, 10, 0, 30, 0, tzinfo=tz)
            mock_dt.now.return_value = fixed_now
            mock_dt.fromisoformat.side_effect = lambda v: datetime.fromisoformat(v)
            result = stats.days_ago(day_value)

    assert result == 1


def test_log_review_writes_day_in_config_tz():
    """db.log_review writes srs_reviews.day as the current date in config.tz."""
    from unittest.mock import MagicMock, Mock, patch
    from zoneinfo import ZoneInfo

    import english_tutor.db as db_mod

    tz = ZoneInfo("Europe/Kyiv")

    # db.log_review imports load_config and ZoneInfo inside the function
    # when day is None. We patch them at the import level.
    with patch("english_tutor.db.ZoneInfo", create=True) as mock_zoneinfo:
        mock_zoneinfo.return_value = tz
        # Mock the datetime module-level import used inside log_review
        # log_review does: from datetime import datetime
        mock_dt = Mock()
        mock_dt.now.return_value = Mock()
        mock_dt.now.return_value.strftime.return_value = "2026-06-10"
        with patch("datetime.datetime", mock_dt):
            mock_conn = MagicMock()
            db_mod.log_review(mock_conn, 42, 1, True)

            call_args = mock_conn.execute.call_args
            actual_day = call_args[0][1][2]
            assert actual_day == "2026-06-10"

