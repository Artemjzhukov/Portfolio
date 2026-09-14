import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from english_tutor import db
from english_tutor.services import srs

logger = logging.getLogger("english_tutor.reminders")

REMINDER_TEXT = (
    "⏰ Время для английского! 🇬🇧\n"
    "У тебя {due} слов к повторению (/review) и урок ждёт (/lessons)."
)


def should_send(now_hhmmss: str, reminder_times: list[str]) -> str | None:
    """Return the slot (e.g. '13:00') that is due at this minute, else None."""
    hhmm = now_hhmmss[:5]
    for slot in reminder_times:
        slot = slot.strip()
        if slot and hhmm == slot:
            return slot
    return None


def is_weekly_due(now, weekly_day: str, weekly_time: str) -> bool:
    return (
        now.strftime("%A").lower() == weekly_day.strip().lower()
        and now.strftime("%H:%M") == weekly_time.strip()
    )


async def reminder_loop(bot, conn, config, admin_id: int, poll_seconds: int = 30) -> None:
    tz = ZoneInfo(config.tz)
    while True:
        try:
            now = datetime.now(tz)
            slot = should_send(now.strftime("%H:%M:%S"), config.reminder_times)
            if slot:
                today = str(now.date())
                for student in db.list_students(conn, "active"):
                    if db.reminder_sent(conn, student["tg_id"], today, slot):
                        continue
                    due = len(srs.due_cards(conn, student["tg_id"]))
                    try:
                        await bot.send_message(
                            student["tg_id"], REMINDER_TEXT.format(due=due)
                        )
                    except Exception:
                        logger.exception("reminder send failed for %s", student["tg_id"])
                    db.mark_reminder_sent(conn, student["tg_id"], today, slot)
            if is_weekly_due(now, config.weekly_summary_day, config.weekly_summary_time):
                week_key = f"weekly-{now.strftime('%G-W%V')}"
                if not db.reminder_sent(conn, admin_id, str(now.date()), week_key):
                    from english_tutor.services import stats

                    body = stats.format_weekly_lines(conn)
                    try:
                        await bot.send_message(
                            admin_id,
                            "📊 Недельный отчёт:\n" + (body or "За неделю активности нет."),
                        )
                    except Exception:
                        logger.exception("weekly summary send failed")
                    db.mark_reminder_sent(conn, admin_id, str(now.date()), week_key)
        except Exception:
            logger.exception("reminder loop error")
        await asyncio.sleep(poll_seconds)
