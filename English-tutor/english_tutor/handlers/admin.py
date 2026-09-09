from aiogram import Router
from aiogram.filters import Command

from english_tutor import db
from english_tutor.services import invites

router = Router()


@router.message(Command("invite"))
async def invite(message, conn):
    code = invites.create_invite(conn)
    await message.answer(f"Новый код приглашения: {code}")


@router.message(Command("approve"))
async def approve(message, conn):
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


@router.message(Command("students"))
async def students(message, conn):
    rows = db.list_students(conn)
    if not rows:
        await message.answer("Пока нет студентов.")
        return
    lines = [f"{r['tg_id']} — {r['name'] or '—'} — {r['status']} — {r['level'] or '—'}"
             for r in rows]
    await message.answer("\n".join(lines))
