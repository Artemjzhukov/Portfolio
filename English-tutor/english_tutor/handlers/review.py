from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from english_tutor import db
from english_tutor.services import exercises, srs

router = Router()


class Review(StatesGroup):
    active = State()


class MaterialSelect(StatesGroup):
    active = State()


def _guard(message, conn):
    student = db.get_student(conn, message.from_user.id)
    return student if student and student["status"] == "active" else None


@router.message(Command("review"))
async def review_cmd(message, state: FSMContext, conn):
    if _guard(message, conn) is None:
        await message.answer("Сначала нужно пройти тест: /start")
        return
    cards = srs.due_cards(conn, message.from_user.id)
    if not cards:
        await message.answer("Дежурных слов нет 🎉 Загляни позже или пройди урок: /lessons")
        return
    await state.set_state(Review.active)
    await state.update_data(card_ids=[c["id"] for c in cards], done=0, correct=0)
    await message.answer(f"Повторение! Слов: {len(cards)}. Отвечай текстом или голосом 🎤")
    # discoverability for material-specific review
    mats = db.list_materials(conn, message.from_user.id)
    has_mat = any(srs.due_cards_by_material(conn, message.from_user.id, m["id"]) for m in mats)
    if has_mat:
        await message.answer("Повторение по материалу: /reviewmaterial")
    await message.answer(srs.format_question(cards[0]))


@router.message(Review.active)
async def review_flow(message, state: FSMContext, conn, llm):
    from english_tutor.handlers.voice import save_and_transcribe
    from english_tutor.services import limits

    data = await state.get_data()
    idx = data["done"]
    card = srs.get_card(conn, data["card_ids"][idx])
    given = message.text
    if given is None:
        voice = getattr(message, "voice", None)
        if voice is None:
            await message.answer("Ответь текстом или голосом 🎤")
            return
        verr = limits.check_voice(voice)
        if verr:
            await message.answer(verr)
            return
        if not limits.can_use_llm(conn, message.from_user.id):
            await message.answer("Дневной лимит запросов исчерпан, попробуй завтра. 🌙")
            return
        limits.register_llm_call(conn, message.from_user.id)
        given = await save_and_transcribe(message, message.bot, llm)
        if not given.strip():
            await message.answer("Не расслышал 🎤 Попробуй ещё раз.")
            return
    correct = exercises.normalize(given) == exercises.normalize(card["word_en"])
    srs.answer_card(conn, card["id"], correct)
    db.log_review(conn, message.from_user.id, card["id"], correct)
    data["done"] = idx + 1
    data["correct"] = data["correct"] + (1 if correct else 0)
    feedback = srs.format_feedback(card, correct)
    if data["done"] < len(data["card_ids"]):
        nxt = srs.get_card(conn, data["card_ids"][data["done"]])
        await state.update_data(done=data["done"], correct=data["correct"])
        await message.answer(feedback + "\n\n" + srs.format_question(nxt))
    else:
        await state.clear()
        more = srs.due_cards(conn, message.from_user.id)
        if more:
            await message.answer(
                f"{feedback}\n\nГотово! {data['correct']}/{len(data['card_ids'])} верно. "
                "Ещё есть слова к повторению: /review"
            )
        else:
            await message.answer(f"{feedback}\n\nГотово! {data['correct']}/{len(data['card_ids'])} верно 🎉")

@router.message(Command("reviewmaterial"))
async def review_material_cmd(message, state: FSMContext, conn):
    if _guard(message, conn) is None:
        await message.answer("Сначала нужно пройти тест: /start")
        return
    materials = db.list_materials(conn, message.from_user.id)
    eligible = []
    for m in materials:
        cards = srs.due_cards_by_material(conn, message.from_user.id, m["id"])
        if cards:
            eligible.append((m, cards))
    if not eligible:
        await message.answer("Нет материалов с карточками к повторению.")
        return
    lines = ["Выбери материал (номер):"]
    for i, (m, cards) in enumerate(eligible, 1):
        title = m["title"] or "material"
        lines.append(f"{i}. {title} ({len(cards)} карточек)")
    await state.set_state(MaterialSelect.active)
    await state.update_data(eligible=[(m["id"], [c["id"] for c in cards]) for m, cards in eligible])
    await message.answer("\n".join(lines))


@router.message(MaterialSelect.active)
async def review_material_select(message, state: FSMContext, conn):
    data = await state.get_data()
    eligible = data.get("eligible", [])
    text = (message.text or "").strip()
    if not text.isdigit() or not (1 <= int(text) <= len(eligible)):
        await message.answer("Ответь номером из списка.")
        return
    idx = int(text) - 1
    material_id, card_ids = eligible[idx]
    await state.set_state(Review.active)
    await state.update_data(card_ids=card_ids, done=0, correct=0)
    card = srs.get_card(conn, card_ids[0])
    await message.answer(f"Повторение по материалу. Слов: {len(card_ids)}.")
    await message.answer(srs.format_question(card))

