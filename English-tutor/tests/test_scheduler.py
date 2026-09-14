
import pytest

from english_tutor import db, scheduler
from english_tutor.services import srs


def test_should_send_matches_slot():
    assert scheduler.should_send("13:00:00", ["13:00", "19:00"]) == "13:00"
    assert scheduler.should_send("19:00:30", ["13:00", "19:00"]) == "19:00"
    assert scheduler.should_send("12:59:59", ["13:00", "19:00"]) is None
    assert scheduler.should_send("08:00:00", []) is None


def test_should_send_tolerates_spaces():
    assert scheduler.should_send("19:00:00", ["13:00, 19:00".split(",")[0], " 19:00"]) == "19:00"


def test_is_weekly_due():
    from datetime import datetime

    sunday_1900 = datetime(2026, 9, 13, 19, 0, 0)  # a Sunday
    assert scheduler.is_weekly_due(sunday_1900, "sunday", "19:00") is True
    assert scheduler.is_weekly_due(sunday_1900, "Sunday", "19:00") is True
    assert scheduler.is_weekly_due(sunday_1900, "sunday", "20:00") is False
    assert scheduler.is_weekly_due(sunday_1900, "monday", "19:00") is False
    monday = datetime(2026, 9, 14, 19, 0, 0)
    assert scheduler.is_weekly_due(monday, "sunday", "19:00") is False


async def test_weekly_summary_sent_to_admin_once(conn):
    db.upsert_student(conn, 42, status="active", level="A2")
    srs = pytest.importorskip("english_tutor.services.srs")
    srs.ensure_card(conn, 42, "cat", "кошка")

    class FakeBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text):
            self.sent.append((chat_id, text))

    bot = FakeBot()
    cfg = type("C", (), {"tz": "Europe/Kiev", "reminder_times": [],
                         "weekly_summary_day": "sunday", "weekly_summary_time": "19:00"})()

    import asyncio
    from datetime import datetime
    from unittest.mock import patch

    fixed = datetime(2026, 9, 13, 19, 0, 10)  # Sunday 19:00
    real_sleep = asyncio.sleep
    with patch("english_tutor.scheduler.datetime") as mock_dt, \
            patch("english_tutor.scheduler.asyncio.sleep", new=lambda s: real_sleep(0)):
        mock_dt.now.return_value = fixed
        task = asyncio.create_task(
            scheduler.reminder_loop(bot, conn, cfg, admin_id=99, poll_seconds=0)
        )
        await asyncio.sleep(0.1)
        task.cancel()

    assert len(bot.sent) == 1
    assert bot.sent[0][0] == 99
    assert "Недельный отчёт" in bot.sent[0][1] and "42" in bot.sent[0][1]
    # dedup: a second tick must not resend
    task2 = asyncio.create_task(
        scheduler.reminder_loop(bot, conn, cfg, admin_id=99, poll_seconds=0)
    )
    await asyncio.sleep(0.1)
    task2.cancel()
    assert len(bot.sent) == 1


def test_reminder_dedup(conn):
    db.upsert_student(conn, 42, status="active", level="A2")
    assert not db.reminder_sent(conn, 42, "2026-09-11", "13:00")
    db.mark_reminder_sent(conn, 42, "2026-09-11", "13:00")
    assert db.reminder_sent(conn, 42, "2026-09-11", "13:00")
    # different day/slot still unsent
    assert not db.reminder_sent(conn, 42, "2026-09-11", "19:00")
    assert not db.reminder_sent(conn, 42, "2026-09-12", "13:00")


async def test_reminder_loop_sends_once_per_slot(conn):
    db.upsert_student(conn, 42, status="active", level="A2")
    srs.ensure_card(conn, 42, "cat", "кошка")
    from datetime import date

    conn.execute(
        "UPDATE srs_cards SET due_date=? WHERE word_en='cat'",
        (str(date.today()),),
    )
    conn.commit()

    class FakeBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text):
            self.sent.append((chat_id, text))

    bot = FakeBot()
    cfg = type("C", (), {"tz": "Europe/Kiev", "reminder_times": ["13:00"]})()

    # run a single tick by simulating: call the inner logic via one short poll
    import asyncio
    from datetime import datetime
    from unittest.mock import patch

    fixed = datetime(2026, 9, 11, 13, 0, 5)
    real_sleep = asyncio.sleep
    with patch("english_tutor.scheduler.datetime") as mock_dt, \
            patch("english_tutor.scheduler.asyncio.sleep", new=lambda s: real_sleep(0)):
        mock_dt.now.return_value = fixed
        task = asyncio.create_task(
            scheduler.reminder_loop(bot, conn, cfg, admin_id=99, poll_seconds=0)
        )
        await asyncio.sleep(0.1)
        task.cancel()

    assert len(bot.sent) == 1
    chat_id, text = bot.sent[0]
    assert chat_id == 42 and "1 слов" in text
