import json
import random

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from english_tutor import db
from english_tutor.services import limits, spine, srs, stories
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
    q_idx = data.get("q_idx", 0)
    correct = data.get("correct", 0)
    if story is None:
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
    if q_idx < len(questions):
        await state.update_data(q_idx=q_idx, correct=correct)
        await message.answer(feedback + "\n\n" + _format_question(questions[q_idx], q_idx))
        return
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
    from english_tutor.handlers.voice import save_and_transcribe

    data = await state.get_data()
    story = data.get("story")
    story_id = data.get("story_id")
    correct = data.get("correct", 0)
    if story is None:
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
    transcript = await save_and_transcribe(message, message.bot, llm)
    if not transcript.strip():
        await message.answer("Не расслышал 🎤 Попробуй ещё раз.")
        return
    result = stories.evaluate_retell(story["target_chunk"], transcript)
    total = len(story["comprehension_questions"])
    db.record_story_progress(
        conn, message.from_user.id, story_id, correct, transcript, result["passed"]
    )
    for item in story.get("glossary", []):
        srs.ensure_card(conn, message.from_user.id, item["en"], item["ru"])
    await state.clear()
    await message.answer(
        f"📝 Расшифровка: {transcript}\n\n"
        f"{result['feedback']}\n\n"
        f"Понимание текста: {correct}/{total}. "
        f"💡 Фразы из глоссария добавлены в /review."
    )
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
    await state.set_state(StorySession.answering_questions)
    await state.update_data(story_id=story_id, story=story, q_idx=0, correct=0)
    for part in split_for_telegram(stories.format_story(story)):
        await message.answer(part)
