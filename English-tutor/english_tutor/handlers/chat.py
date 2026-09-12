import random

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from english_tutor import db
from english_tutor.handlers.voice import save_and_transcribe
from english_tutor.services import chat as chat_svc
from english_tutor.services import limits, spine, srs
from english_tutor.utils.telegram import split_for_telegram

router = Router()


class Chat(StatesGroup):
    active = State()


@router.message(Command("chat"))
async def chat_cmd(message, state: FSMContext, conn):
    student = db.get_student(conn, message.from_user.id)
    if not student or student["status"] != "active":
        await message.answer("Сначала нужно пройти тест: /start")
        return
    topics = random.sample(spine.topics(student["level"]), k=min(3, len(spine.topics(student["level"]))))
    await state.set_state(Chat.active)
    await message.answer(
        "Поговорим по-английски! 🇬🇧 Темы на выбор:\n"
        + "\n".join(f"• {t}" for t in topics)
        + "\n\nИли пиши о чём угодно — текстом или голосом. /cancel — выйти."
    )


@router.message(Chat.active)
async def chat_flow(message, state: FSMContext, conn, llm):
    student = db.get_student(conn, message.from_user.id)
    if student is None or student["status"] != "active":
        await state.clear()
        return
    text = (message.text or "").strip()
    if text.startswith("/"):
        await state.clear()
        await message.answer("Вышел из чата. /lessons — уроки, /review — слова, /drill — говорение.")
        return
    if text:
        err = limits.check_text(text)
        if err:
            await message.answer(err)
            return
    else:
        voice = getattr(message, "voice", None)
        if voice is None:
            await message.answer("Напиши сообщение или отправь голосовое 🎤")
            return
        verr = limits.check_voice(voice)
        if verr:
            await message.answer(verr)
            return
        if not limits.can_use_llm(conn, student["tg_id"]):
            await message.answer("Дневной лимит запросов исчерпан, попробуй завтра. 🌙")
            return
        limits.register_llm_call(conn, student["tg_id"])
        text = await save_and_transcribe(message, message.bot, llm)
        if not text.strip():
            await message.answer("Не расслышал 🎤 Попробуй ещё раз.")
            return
    if not limits.can_use_llm(conn, student["tg_id"]):
        await message.answer("Дневной лимит запросов исчерпан, попробуй завтра. 🌙")
        return
    limits.register_llm_call(conn, student["tg_id"])
    try:
        data = chat_svc.parse_chat(
            await llm.chat_json_async(chat_svc.chat_system_prompt(student["level"]), text)
        )
    except Exception:
        await message.answer("Проблема с сервисом языка, попробуй ещё раз через минуту. 🛠")
        return
    for c in data.get("corrections", []):
        db.insert_correction(
            conn, student["tg_id"], c["wrong"], c["right"], c["hint_ru"], source="chat"
        )
        srs.ensure_card(conn, student["tg_id"], c["right"], c["hint_ru"])
    for part in split_for_telegram(chat_svc.format_chat_answer(data)):
        await message.answer(part)
