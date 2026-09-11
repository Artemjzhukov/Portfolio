import pytest

from english_tutor import db
from english_tutor.services import srs


@pytest.fixture
def student(conn):
    db.upsert_student(conn, 42, status="active", level="B1")
    return 42


def _force_due(conn, card_id):
    from datetime import date

    conn.execute("UPDATE srs_cards SET due_date=? WHERE id=?", (str(date.today()), card_id))
    conn.commit()


def _card(conn, tg_id, word_en):
    return conn.execute(
        "SELECT * FROM srs_cards WHERE student_id=? AND word_en=?", (tg_id, word_en)
    ).fetchone()


def test_ensure_card_creates_once(student, conn):
    assert srs.ensure_card(conn, 42, "cat", "кошка") is True
    assert srs.ensure_card(conn, 42, "cat", "кошка") is False  # dedup
    assert srs.ensure_card(conn, 42, "cat ", " кошка") is False  # whitespace-stripped dedup


def test_answer_ladder_progression(student, conn):
    from datetime import date, timedelta

    srs.ensure_card(conn, 42, "cat", "кошка")
    card = _card(conn, 42, "cat")
    # initially not due until tomorrow
    due = date.fromisoformat(card["due_date"])
    assert due == date.today() + timedelta(days=1)
    _force_due(conn, card["id"])
    # answer correct five times → intervals 3,7,14,30,30
    seen = []
    for _ in range(5):
        interval = srs.answer_card(conn, card["id"], True)
        seen.append(interval)
    assert seen == [3, 7, 14, 30, 30]


def test_answer_wrong_resets_ladder(student, conn):
    srs.ensure_card(conn, 42, "dog", "собака")
    card = _card(conn, 42, "dog")
    _force_due(conn, card["id"])
    srs.answer_card(conn, card["id"], True)  # step to 3d
    interval = srs.answer_card(conn, card["id"], False)
    assert interval == 1
    card = srs.get_card(conn, card["id"])
    assert card["interval_index"] == 0


def test_due_cards_filters_and_orders(student, conn):
    from datetime import date, timedelta

    srs.ensure_card(conn, 42, "a", "а")
    srs.ensure_card(conn, 42, "b", "б")
    for c in srs.due_cards(conn, 42):
        pass  # none due yet
    cards = conn.execute("SELECT * FROM srs_cards WHERE student_id=42").fetchall()
    assert len(cards) == 2
    for c in cards:
        conn.execute(
            "UPDATE srs_cards SET due_date=? WHERE id=?",
            (str(date.today() - timedelta(days=1)), c["id"]),
        )
    conn.commit()
    due = srs.due_cards(conn, 42)
    assert len(due) == 2
    assert srs.due_cards(conn, 42, limit=1)[0]["id"] == due[0]["id"]


def test_answer_missing_card_is_none(conn):
    assert srs.answer_card(conn, 999, True) is None


def test_question_and_feedback_formats(student, conn):
    srs.ensure_card(conn, 42, "cat", "кошка")
    card = _card(conn, 42, "cat")
    assert "кошка" in srs.format_question(card)
    assert srs.format_feedback(card, True).startswith("✅")
    assert "cat" in srs.format_feedback(card, False)
