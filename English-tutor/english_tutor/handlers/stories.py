import json
import random

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from english_tutor import db
from english_tutor.services import limits, spine, stories
from english_tutor.utils.telegram import split_for_telegram

router = Router()


class StorySession(StatesGroup):
    answering_questions = State()
    waiting_retell = State()


def _guard(message, conn):
    student = db.get_student(conn, message.from_user.id)
    return student if student and student["status"] == "active" else None


def _format_question(question: dict, idx: int, total: int = 2) -> str:
    lines = [
        f"❓ **Проверка понимания (Вопрос {idx + 1}/{total}):**",
        question["q"],
        "",
        "\n".join(question["options"]),
        "",
        "👉 Ответь числом 1 или 2:",
    ]
    return "\n".join(lines)


def _pick_topic(level: str, raw_topic: str | None) -> str:
    if raw_topic:
        return raw_topic
    topics = spine.topics(level)
    if topics:
        return random.choice(topics)
    return "everyday life"


@router.message(StorySession.answering_questions)
async def story_answer(message, state: FSMContext, conn):
    data = await state.get_data()
    story = data.get("story")
    story_id = data.get("story_id")
    q_idx = data.get("q_idx", 0)
    correct = data.get("correct", 0)
    if story is None or story_id is None:
        await state.clear()
        await message.answer("История потерялась, начни заново: /story")
        return
    questions = story["comprehension_questions"]
    if q_idx >= len(questions):
        await state.clear()
        return
    text = (message.text or "").strip()
    if text not in ("1", "2"):
        await message.answer("👉 Ответь числом 1 или 2:")
        return
    q = questions[q_idx]
    if text == q["answer"]:
        correct += 1
        feedback = "✅ Верно!"
    else:
        feedback = f"❌ Не совсем. Правильно: {q['answer']} ({q['hint_ru']})"
    q_idx += 1
    # Persist progress after every accepted answer
    if q_idx < len(questions):
        db.save_story_session(
            conn, message.from_user.id, story_id, "answering_questions", q_idx, correct
        )
        await state.update_data(q_idx=q_idx, correct=correct)
        await message.answer(feedback + "\n\n" + _format_question(questions[q_idx], q_idx))
        return
    # Transition to voice retelling — persist the stage change
    db.save_story_session(conn, message.from_user.id, story_id, "waiting_retell", q_idx, correct)
    await state.set_state(StorySession.waiting_retell)
    await state.update_data(q_idx=q_idx, correct=correct)
    await message.answer(
        feedback
        + "\n\n🎤 **Задание на говорение (Retell):**\n"
        + story["retell_prompt"]
        + "\n\nНажми микрофон и наговори ответ голосом."
    )


@router.message(StorySession.waiting_retell)
async def story_retell(message, state: FSMContext, conn, llm):
    from english_tutor.handlers.voice import VoiceTranscribeError, save_and_transcribe

    data = await state.get_data()
    story = data.get("story")
    story_id = data.get("story_id")
    correct = data.get("correct", 0)
    if story is None or story_id is None:
        await state.clear()
        await message.answer("История потерялась, начни заново: /story")
        return
    if getattr(message, "voice", None) is None:
        await message.answer("Здесь я жду голосовое сообщение 🎤 Нажми микрофон и перескажи историю.")
        return
    verr = limits.check_voice(message.voice)
    if verr:
        await message.answer(verr)
        return
    if not limits.can_use_llm(conn, message.from_user.id):
        await message.answer("Дневной лимит запросов исчерпан, попробуй завтра. 🌙")
        return
    limits.register_llm_call(conn, message.from_user.id)
    try:
        transcript = await save_and_transcribe(message, message.bot, llm)
    except VoiceTranscribeError:
        await message.answer("Не удалось распознать речь 🎤 Попробуй ещё раз.")
        return
    if not transcript.strip():
        await message.answer("Не расслышал 🎤 Попробуй ещё раз.")
        return
    result = stories.evaluate_retell(story["target_chunk"], transcript)
    total = len(story["comprehension_questions"])
    db.complete_story(
        conn, message.from_user.id, story_id, correct, transcript,
        result["passed"], story.get("glossary", []),
    )
    await state.clear()
    await message.answer(
        f"📝 Расшифровка: {transcript}\n\n"
        f"{result['feedback']}\n\n"
        f"Понимание текста: {correct}/{total}. "
        f"💡 Фразы из глоссария добавлены в /review."
    )


@router.message(Command("cancel"))
async def story_cancel(message, state: FSMContext, conn):
    """Cancel a /story session: clear in-memory FSM and remove durable session."""
    session = db.get_active_session(conn, message.from_user.id)
    if session is not None:
        db.delete_active_session(conn, message.from_user.id)
        await message.answer("🎹 Зачитывание истории отменено. Чтобы начать заново: /story")
    else:
        await message.answer("Отменено. /start — заново, /lessons — уроки, /drill — говорение.")
    await state.clear()
@router.message(Command("story"))
async def story_cmd(message, state: FSMContext, conn, llm):
    student = _guard(message, conn)
    if student is None:
        await message.answer("Сначала пройди регистрацию: /start")
        return
    raw = message.text or ""
    parts = raw.split(maxsplit=1)
    raw_topic = parts[1].strip() if len(parts) > 1 else None
    if raw_topic:
        err = limits.check_theme(raw_topic)
        if err:
            await message.answer(err)
            return
    topic = _pick_topic(student["level"], raw_topic)
    if not limits.can_use_llm(conn, student["tg_id"]):
        await message.answer("Дневной лимит запросов исчерпан, попробуй завтра. 🌙")
        return
    limits.register_llm_call(conn, student["tg_id"])
    try:
        story = await stories.generate_story_async(
            conn, llm, student["level"], topic, student["tg_id"]
        )
    except Exception:
        await message.answer("Проблема с сервисом историй, попробуй ещё раз через минуту. 🛠")
        return
    story_id = db.save_story(
        conn, student["tg_id"], student["level"], topic,
        json.dumps(story, ensure_ascii=False),
    )
    # Persist the new active session so it survives a process restart
    db.save_story_session(conn, student["tg_id"], story_id, "answering_questions")
    await state.set_state(StorySession.answering_questions)
    await state.update_data(story_id=story_id, story=story, q_idx=0, correct=0)
    for part in split_for_telegram(stories.format_story(story)):
        await message.answer(part)


@router.message(Command("resume"))
async def resume_cmd(message, state: FSMContext, conn):
    """Restore an interrupted /story session from durable storage."""
    student = _guard(message, conn)
    if student is None:
        await message.answer("Сначала пройди регистрацию: /start")
        return
    session = db.get_active_session(conn, message.from_user.id)
    if session is None:
        await message.answer("У тебя нет незавершённой истории. Начни: /story")
        return
    story = db.get_story(conn, session["story_id"])
    if story is None or story["student_id"] != student["tg_id"]:
        db.delete_active_session(conn, message.from_user.id)
        await state.clear()
        await message.answer("Сессия повреждена, начни заново: /story")
        return
    story_data = json.loads(story["content_json"])
    if session["stage"] == "answering_questions":
        if session["q_idx"] >= len(story_data["comprehension_questions"]):
            await state.set_state(StorySession.waiting_retell)
            await state.update_data(
                story_id=session["story_id"], story=story_data,
                q_idx=session["q_idx"], correct=session["correct"],
            )
            await message.answer(
                "🎤 **Задание на говорение (Retell):**\n"
                + story_data["retell_prompt"]
                + "\n\nНажми микрофон и наговори ответ голосом."
            )
            return
        await state.set_state(StorySession.answering_questions)
        await state.update_data(
            story_id=session["story_id"], story=story_data,
            q_idx=session["q_idx"], correct=session["correct"],
        )
        questions = story_data["comprehension_questions"]
        await message.answer(
            f"📖 Продолжаем историю! Вопрос {session['q_idx'] + 1}/{len(questions)}:\n"
            + _format_question(questions[session["q_idx"]], session["q_idx"])
        )
    else:
        await state.set_state(StorySession.waiting_retell)
        await state.update_data(
            story_id=session["story_id"], story=story_data,
            q_idx=session["q_idx"], correct=session["correct"],
        )
        await message.answer(
            "🎤 Давай дай ответ голосом — перескажи историю.\n"
            + story_data["retell_prompt"]
        )
