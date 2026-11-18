import json
import logging
import random

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from english_tutor import db
from english_tutor.services import exercises, lessons, limits, spine, srs, stats
from english_tutor.utils.telegram import split_for_telegram

router = Router()
logger = logging.getLogger(__name__)


class LessonResume(StatesGroup):
    choosing = State()


class LessonSession(StatesGroup):
    active = State()
    voice_task = State()


class Drill(StatesGroup):
    active = State()


@router.message(Command("cancel"))
async def cancel(message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено. /start — заново, /lessons — уроки, /drill — говорение.")

@router.message(Command("resume"))
async def resume_cmd(message, state: FSMContext, conn):
    student = db.get_student(conn, message.from_user.id)
    if not student or student["status"] != "active":
        await message.answer("Сначала нужно пройти тест: /start")
        return
    ls = db.get_lesson_session(conn, message.from_user.id)
    ss = db.get_active_session(conn, message.from_user.id)
    if ls is None and ss is None:
        await message.answer("Незавершённых сессий нет. /story — история, /lessons — уроки.")
        return
    if ls is not None and ss is not None:
        await message.answer("Есть и урок, и история. Выбери: /lessons или /resume story")
        return
    if ls is not None:
        row = conn.execute(
            "SELECT content_json FROM lessons WHERE id=?", (ls["lesson_id"],)
        ).fetchone()
        if row is None:
            db.delete_lesson_session(conn, message.from_user.id)
            await message.answer("Сессия повреждена. /lessons")
            return
        lesson = json.loads(row["content_json"])
        meta = {
            "kind": ls["kind"],
            "level": ls["level"],
            "topic": ls["topic"],
            "student_id": None,
        }
        await state.set_state(
            LessonSession.active if ls["stage"] == "exercising" else LessonSession.voice_task
        )
        await state.update_data(
            lesson=lesson,
            ex_idx=ls["ex_idx"],
            correct=ls["correct"],
            meta=meta,
            voice_task=lesson.get("voice_task", ""),
        )
        await message.answer("Восстановлен урок.")
        if ls["stage"] == "exercising" and ls["ex_idx"] < len(lesson["exercises"]):
            await message.answer(
                lessons.format_exercise_prompt(
                    lesson["exercises"][ls["ex_idx"]], ls["ex_idx"] + 1
                )
            )
        else:
            await message.answer(lesson.get("voice_task", ""))
        return
    # story
    from english_tutor.handlers import stories

    await stories.resume_cmd(message, state, conn)


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
    session = db.get_lesson_session(conn, message.from_user.id)
    if session is not None:
        await state.set_state(LessonResume.choosing)
        await state.update_data(session=session)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Продолжить", callback_data="lesson:continue")],
            [InlineKeyboardButton(text="🆕 Новый урок", callback_data="lesson:new")],
            [InlineKeyboardButton(text="🏠 Меню", callback_data="lesson:menu")],
        ])
        await message.answer("Есть незавершённый урок. Продолжить?", reply_markup=kb)
        return
    await state.set_state(LessonSession.active)
    await state.update_data(ex_idx=None, lesson=None)
    await message.answer(_menu(student["level"]))


@router.message(Command("mylevel"))
async def mylevel_cmd(message, state: FSMContext, conn):
    student = _guard(message, conn, state)
    if student is None:
        await message.answer("Сначала нужно пройти тест: /start")
        return
    level = student["level"]
    done = stats.spine_completed_topics(conn, message.from_user.id, level)
    total = len(spine.topics(level))
    due = len(srs.due_cards(conn, message.from_user.id))
    lines = [
        f"Твой уровень: {level}",
        f"Пройдено тем уровня: {len(done)}/{total}",
        f"Слов к повторению: {due} (/review)",
    ]
    if len(done) >= 5 and level == "B2":
        lines.append("\n🏆 Это максимальный уровень бота — отличная работа!")
    elif len(done) >= 5:
        lines.append("\n🎓 Ты почти готов к уровню выше — переаттестация откроется скоро!")
    await message.answer("\n".join(lines))


@router.message(Command("drill"))
async def drill_cmd(message, state: FSMContext, conn):
    student = _guard(message, conn, state)
    if student is None:
        await message.answer("Сначала нужно пройти тест: /start")
        return
    topic = random.choice(lessons.DRILL_PROMPTS)
    await state.set_state(Drill.active)
    await message.answer(lessons.format_drill_prompt(topic))


async def _resolve_lesson(message, conn, llm, student):
    text = (message.text or "").strip()
    level_topics = spine.topics(student["level"])
    if text.isdigit() and 1 <= int(text) <= len(level_topics):
        topic, kind = level_topics[int(text) - 1], "curriculum"
    else:
        topic, kind = text, "theme"
    kwargs = dict(
        level=student["level"], topic=topic, kind=kind,
        student_id=student["tg_id"] if kind == "theme" else None,
    )
    try:
        lesson = await lessons.get_or_create_lesson_async(conn, llm, **kwargs)
        meta = dict(kind=kind, level=student["level"], topic=topic, student_id=kwargs["student_id"])
        return lesson, meta
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
        lesson_meta = await _resolve_lesson(message, conn, llm, student)
        if lesson_meta is None:
            await message.answer("Не получилось составить урок, попробуй другую тему.")
            return
        lesson, meta = lesson_meta
        limits.register_llm_call(conn, student["tg_id"])
        for part in split_for_telegram(lessons.format_lesson(lesson)):
            await message.answer(part)
        lid = lessons.find_lesson_id(
            conn,
            meta.get("kind", "theme"),
            meta.get("level", ""),
            meta.get("topic", ""),
            meta.get("student_id"),
        )
        if lid:
            db.save_lesson_session(
                conn,
                message.from_user.id,
                lid,
                meta.get("kind", "theme"),
                meta.get("level", ""),
                meta.get("topic", ""),
                "exercising",
                0,
                0,
            )
        await state.update_data(lesson=lesson, ex_idx=0, correct=0, meta=meta)
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
    data["correct"] = data.get("correct", 0) + (1 if ok else 0)
    if ok:
        reply = "✅ Верно!"
    else:
        reply = f"❌ Не совсем. Правильно: {exercise['answer']} ({exercise['hint_ru']})"
    await message.answer(reply)
    nxt = data["ex_idx"] + 1
    if nxt < len(data["lesson"]["exercises"]):
        await state.update_data(ex_idx=nxt, correct=data["correct"])
        meta = data.get("meta", {})
        lid = lessons.find_lesson_id(
            conn,
            meta.get("kind", "theme"),
            meta.get("level", ""),
            meta.get("topic", ""),
            meta.get("student_id"),
        )
        if lid:
            db.save_lesson_session(
                conn,
                message.from_user.id,
                lid,
                meta.get("kind", "theme"),
                meta.get("level", ""),
                meta.get("topic", ""),
                "exercising",
                nxt,
                data["correct"],
            )
        next_ex = data["lesson"]["exercises"][nxt]
        await message.answer(lessons.format_exercise_prompt(next_ex, nxt + 1))
    else:
        # lesson complete: vocab → SRS deck, K1 progress row
        vocab_items = data["lesson"].get("vocab", [])
        for w in vocab_items:
            srs.ensure_card(conn, message.from_user.id, w["en"], w["ru"])
        meta = data.get("meta", {})
        lesson_id = lessons.find_lesson_id(
            conn, meta.get("kind", "curriculum"), meta.get("level", ""),
            meta.get("topic", ""), meta.get("student_id"),
        )
        if lesson_id:
            db.record_progress(conn, message.from_user.id, lesson_id, "completed", data["correct"])
        finish_text = (
            f"🎉 Урок пройден! Результат: {data['correct']}/{len(data['lesson']['exercises'])}\n\n"
            f"💡 В твой словарь повторения (/review) добавлено {len(vocab_items)} выражений.\n"
            f"🎤 Финальное разговорное задание:\n{data['lesson']['voice_task']}\n\n"
            "Наговори голосовое в ответ или выбери следующий шаг: /lessons, /drill, /chat."
        )
        meta = data.get("meta", {})
        lid = lessons.find_lesson_id(
            conn,
            meta.get("kind", "theme"),
            meta.get("level", ""),
            meta.get("topic", ""),
            meta.get("student_id"),
        )
        if lid:
            db.delete_lesson_session(conn, message.from_user.id)
        await message.answer(finish_text)
        await state.set_state(LessonSession.voice_task)
        await state.update_data(
            lesson=data.get("lesson"),
            meta=meta,
            voice_task=data.get("lesson", {}).get("voice_task", ""),
        )
        if lid:
            db.save_lesson_session(
                conn,
                message.from_user.id,
                lid,
                meta.get("kind", "theme"),
                meta.get("level", ""),
                meta.get("topic", ""),
                "voice_task",
                len(data.get("lesson", {}).get("exercises", [])),
                data["correct"],
            )



@router.callback_query(lambda c: c.data == "lesson:continue")
async def cb_lesson_continue(cb: CallbackQuery, state: FSMContext, conn):
    data = await state.get_data()
    session = data.get("session") or db.get_lesson_session(conn, cb.from_user.id)
    if session is None:
        await cb.answer("Сессия не найдена")
        return
    row = conn.execute(
        "SELECT content_json FROM lessons WHERE id=?", (session["lesson_id"],)
    ).fetchone()
    if row is None:
        db.delete_lesson_session(conn, cb.from_user.id)
        await cb.message.answer("Урок потерян. Начни заново: /lessons")
        await state.clear()
        await cb.answer()
        return
    lesson = json.loads(row["content_json"])
    meta = {
        "kind": session["kind"],
        "level": session["level"],
        "topic": session["topic"],
        "student_id": None,
    }
    await state.set_state(LessonSession.active)
    await state.update_data(
        lesson=lesson, ex_idx=session["ex_idx"], correct=session["correct"], meta=meta
    )
    await cb.message.answer("Продолжаем урок.")
    if session["ex_idx"] < len(lesson["exercises"]):
        await cb.message.answer(
            lessons.format_exercise_prompt(
                lesson["exercises"][session["ex_idx"]], session["ex_idx"] + 1
            )
        )
    else:
        await cb.message.answer(lesson.get("voice_task", ""))
    await cb.answer()


@router.callback_query(lambda c: c.data == "lesson:new")
async def cb_lesson_new(cb: CallbackQuery, state: FSMContext, conn):
    db.delete_lesson_session(conn, cb.from_user.id)
    await state.clear()
    await cb.message.answer("Начинаем новый урок. Выбери тему:")
    student = db.get_student(conn, cb.from_user.id)
    if student:
        await cb.message.answer(_menu(student["level"]))
        await state.set_state(LessonSession.active)
        await state.update_data(ex_idx=None, lesson=None)
    await cb.answer()


@router.callback_query(lambda c: c.data == "lesson:menu")
async def cb_lesson_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("Главное меню.")
    await cb.answer()

@router.message(LessonSession.voice_task)
async def lesson_voice_task(message, state, conn, llm):
    from english_tutor.handlers.voice import save_and_transcribe
    from english_tutor.services import limits
    from english_tutor.services.grammar_feedback import (
        MIN_TRANSCRIPT_WORDS,
        analyze_grammar,
        format_feedback,
    )

    data = await state.get_data()
    meta = data.get("meta") or {}
    if getattr(message, "voice", None) is None:
        await message.answer("Жду голосовое 🎤 " + data.get("voice_task", ""))
        return
    err = limits.check_voice(message.voice)
    if err:
        await message.answer(err)
        return
    # One atomic reservation per real LLM call: Whisper transcription first.
    if not limits.try_reserve_llm(conn, message.from_user.id):
        await message.answer("Дневной лимит запросов исчерпан.")
        return
    try:
        transcript = await save_and_transcribe(message, message.bot, llm)
    except Exception:
        await message.answer("Не удалось распознать. Попробуй ещё раз.")
        return
    if not (transcript or "").strip():
        await message.answer("Не расслышал 🎤 Попробуй ещё раз.")
        return
    await message.answer(f"📝 Расшифровка: {transcript}")

    # Stage 4G.2: grammar feedback is best-effort and never blocks completion.
    # A quota unit is reserved only when the analysis will really call the LLM;
    # a transcript that is too short produces a local message instead.
    enough_context = len(transcript.split()) >= MIN_TRANSCRIPT_WORDS
    if not enough_context or limits.try_reserve_llm(conn, message.from_user.id):
        try:
            feedback = await analyze_grammar(
                transcript,
                llm,
                task_description=(
                    data.get("voice_task") or (data.get("lesson") or {}).get("voice_task")
                ),
                student_level=meta.get("level"),
                pattern_ids=data.get("pattern_ids"),
            )
        except Exception:
            logger.warning("Grammar feedback failed", exc_info=True)
            feedback = None
        feedback_text = format_feedback(feedback)
        if feedback_text:
            for chunk in split_for_telegram(feedback_text):
                await message.answer(chunk)

    await message.answer("Задание завершено. /lessons — новый урок, /drill — говорение.")
    db.delete_lesson_session(conn, message.from_user.id)
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
