import random

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from english_tutor import db
from english_tutor.services import exercises, lessons, limits, spine

router = Router()


class LessonSession(StatesGroup):
    active = State()


class Drill(StatesGroup):
    active = State()


def _menu(level: str) -> str:
    lines = [f"{i}. {t}" for i, t in enumerate(spine.topics(level), 1)]
    return "Выбери тему урока (номер) или напиши свою тему:\n" + "\n".join(lines)


def _guard(message, conn, state):
    student = db.get_student(conn, message.from_user.id)
    if not student or student["status"] != "active":
        return None
    return student


@router.message(Command("lessons"))
async def lessons_cmd(message, state: FSMContext, conn):
    student = _guard(message, conn, state)
    if student is None:
        await message.answer("Сначала нужно пройти тест: /start")
        return
    await state.set_state(LessonSession.active)
    await state.update_data(ex_idx=None, lesson=None)
    await message.answer(_menu(student["level"]))


@router.message(Command("drill"))
async def drill_cmd(message, state: FSMContext, conn):
    student = _guard(message, conn, state)
    if student is None:
        await message.answer("Сначала нужно пройти тест: /start")
        return
    topic = random.choice(lessons.DRILL_PROMPTS)
    await state.set_state(Drill.active)
    await message.answer(lessons.format_drill_prompt(topic))


def _resolve_lesson(message, conn, llm, student):
    text = (message.text or "").strip()
    level_topics = spine.topics(student["level"])
    if text.isdigit() and 1 <= int(text) <= len(level_topics):
        topic, kind = level_topics[int(text) - 1], "curriculum"
    else:
        topic, kind = text, "theme"
    try:
        return lessons.get_or_create_lesson(
            conn, llm, level=student["level"], topic=topic, kind=kind,
            student_id=student["tg_id"] if kind == "theme" else None,
        )
    except lessons.LessonFormatError:
        return None


@router.message(LessonSession.active)
async def lesson_flow(message, state: FSMContext, conn, llm):
    data = await state.get_data()
    student = db.get_student(conn, message.from_user.id)
    if data.get("ex_idx") is None:
        text = (message.text or "").strip()
        if not text.isdigit():
            err = limits.check_theme(text) or limits.check_text(text)
            if err:
                await message.answer(err)
                return
        if not limits.can_use_llm(conn, student["tg_id"]):
            await message.answer("Дневной лимит запросов исчерпан, попробуй завтра. 🌙")
            return
        lesson = _resolve_lesson(message, conn, llm, student)
        if lesson is None:
            await message.answer("Не получилось составить урок, попробуй другую тему.")
            return
        limits.register_llm_call(conn, student["tg_id"])
        await message.answer(lessons.format_lesson(lesson))
        await state.update_data(lesson=lesson, ex_idx=0)
        return
    err = limits.check_text(message.text)
    if err:
        await message.answer(err)
        return
    answer_text = message.text
    if answer_text is None:
        if getattr(message, "voice", None) is not None:
            verr = limits.check_voice(message.voice)
            if verr:
                await message.answer(verr)
                return
            if not limits.can_use_llm(conn, message.from_user.id):
                await message.answer("Дневной лимит запросов исчерпан, попробуй завтра. 🌙")
                return
            limits.register_llm_call(conn, message.from_user.id)
            from english_tutor.handlers.voice import save_and_transcribe

            answer_text = await save_and_transcribe(message, message.bot, llm)
        else:
            await message.answer("Ответь текстом или голосом 🎤")
            return
    exercise = data["lesson"]["exercises"][data["ex_idx"]]
    ok = exercises.check_answer(exercise, answer_text)
    if ok:
        reply = "✅ Верно!"
    else:
        reply = f"❌ Не совсем. Правильно: {exercise['answer']} ({exercise['hint_ru']})"
    await message.answer(reply)
    nxt = data["ex_idx"] + 1
    if nxt < len(data["lesson"]["exercises"]):
        await state.update_data(ex_idx=nxt)
        await message.answer(data["lesson"]["exercises"][nxt]["prompt"])
    else:
        await message.answer("Урок пройден! /lessons — следующая тема, /drill — speaking practice.")
        await state.clear()


@router.message(Drill.active)
async def drill_flow(message, state: FSMContext, conn, llm):
    from english_tutor.handlers.voice import save_and_transcribe

    if getattr(message, "voice", None) is None:
        await message.answer(
            "Здесь я жду голосовое сообщение 🎤 Нажми микрофон и ответь. "
            "Или /drill, чтобы получить задание ещё раз."
        )
        return
    err = limits.check_voice(message.voice)
    if err:
        await message.answer(err)
        return
    if not limits.can_use_llm(conn, message.from_user.id):
        await message.answer("Дневной лимит запросов исчерпан, попробуй завтра. 🌙")
        return
    limits.register_llm_call(conn, message.from_user.id)
    transcript = await save_and_transcribe(message, message.bot, llm)
    await message.answer(f"📝 Расшифровка: {transcript}\n\n(Разбор ошибок появится в Phase 2)")
    await state.clear()
