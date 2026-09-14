from aiogram import Router
from aiogram.filters import Command

from english_tutor import db
from english_tutor.services import invites, stats
from english_tutor.utils.telegram import split_for_telegram

router = Router()


def _is_admin(message, admin_id) -> bool:
    return getattr(message.from_user, "id", None) == admin_id


@router.message(Command("invite"))
async def invite(message, conn, admin_id):
    if not _is_admin(message, admin_id):
        await message.answer("Эта команда только для админа.")
        return
    code = invites.create_invite(conn)
    await message.answer(f"Новый код приглашения: {code}")


@router.message(Command("approve"))
async def approve(message, conn, admin_id):
    if not _is_admin(message, admin_id):
        await message.answer("Эта команда только для админа.")
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        await message.answer("Формат: /approve <tg_id> [A2|B1|B2]")
        return
    tg_id = int(parts[1])
    level = parts[2].upper() if len(parts) > 2 else None
    if level not in ("A2", "B1", "B2"):
        row = conn.execute(
            "SELECT suggested_level FROM test_results WHERE student_id=? "
            "ORDER BY id DESC LIMIT 1",
            (tg_id,),
        ).fetchone()
        level = (row["suggested_level"] if row else None) or "A2"
    db.set_student_level(conn, tg_id, level)
    db.set_student_status(conn, tg_id, "active")
    await message.answer(f"Студент {tg_id} активирован, уровень {level}.")


@router.message(Command("stats"))
async def stats_cmd(message, conn, llm, admin_id):
    if not _is_admin(message, admin_id):
        await message.answer("Эта команда только для админа.")
        return
    parts = (message.text or "").split()
    if len(parts) > 1 and parts[1].lstrip("-").isdigit():
        await _stats_detail(message, conn, llm, int(parts[1]))
        return
    lines = []
    for s in db.list_students(conn, "active"):
        o = stats.overview(conn, s["tg_id"])
        lines.append(
            f"{s['tg_id']} — {s['name'] or '—'} ({o['level'] or '—'}): "
            f"уроков {o['lessons_done']}, слов к повторению {o['cards_due']}"
        )
    await message.answer("\n".join(lines) or "Нет активных студентов.")


async def _stats_detail(message, conn, llm, tg_id: int):
    o = stats.overview(conn, tg_id)
    lines = [
        f"📊 Студент {tg_id} — уровень {o['level'] or '—'}",
        f"Уроков пройдено: {o['lessons_done']} ({o['spine_done']}/{o['spine_total']} тем уровня)",
        f"SRS: всего слов {o['cards_total']}, к повторению {o['cards_due']}",
        (
            f"Точность повторений: {o['retention']}%"
            if o["retention"] is not None
            else "Повторений пока не было"
        ),
        f"Исправлений: {o['corrections']}",
    ]
    cats = await stats.categorize_patterns(conn, tg_id, llm)
    formatted = stats.format_categories(cats or {})
    if formatted:
        lines.append(formatted)
    patterns = stats.error_patterns(conn, tg_id)
    if patterns:
        lines.append("Частые ошибки:")
        for p in patterns:
            lines.append(f"• «{p['wrong']}» → «{p['right']}» ×{p['n']}")
    w = stats.weekly(conn, tg_id)
    lines.append(
        f"За 7 дней: уроков {w['lessons']}, исправлений {w['corrections']}, "
        f"повторений {w['reviews']}"
    )
    for part in split_for_telegram("\n".join(lines)):
        await message.answer(part)
@router.message(Command("students"))
async def students(message, conn, admin_id):
    if not _is_admin(message, admin_id):
        await message.answer("Эта команда только для админа.")
        return
    rows = db.list_students(conn)
    if not rows:
        await message.answer("Пока нет студентов.")
        return
    lines = [f"{r['tg_id']} — {r['name'] or '—'} — {r['status']} — {r['level'] or '—'}"
             for r in rows]
    for part in split_for_telegram("\n".join(lines)):
        await message.answer(part)
