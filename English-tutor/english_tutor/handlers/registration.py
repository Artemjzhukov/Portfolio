from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from english_tutor import db
from english_tutor.services import invites, placement

router = Router()


class Registration(StatesGroup):
    waiting_code = State()
    waiting_name = State()
    test_question = State()
    waiting_voice = State()


def _question_text(idx: int) -> str:
    q = placement.QUESTIONS[idx]
    opts = "\n".join(f"{i}. {o}" for i, o in enumerate(q["options"]))
    return f"Вопрос {idx + 1}/20:\n{q['q']}\n\n{opts}\n\n(ответь номером)"


@router.message(CommandStart())
async def start(message, state: FSMContext, conn):
    await state.clear()
    student = db.get_student(conn, message.from_user.id)
    if student and student["status"] == "active":
        await message.answer("С возвращением! /lessons — меню уроков, /drill — speaking practice.")
        return
    await state.set_state(Registration.waiting_code)
    await message.answer("Доступ по приглашению. Введите код:")


@router.message(Registration.waiting_code)
async def handle_code(message, state: FSMContext, conn):
    code = (message.text or "").strip()
    if code and invites.redeem(conn, code, message.from_user.id):
        await state.set_state(Registration.waiting_name)
        await message.answer("Код принят! Как тебя зовут?")
    else:
        await message.answer("Неверный или уже использованный код. Попробуй ещё:")


@router.message(Registration.waiting_name)
async def handle_name(message, state: FSMContext, conn):
    name = (message.text or "").strip()
    if not name:
        await message.answer("Напиши своё имя текстом:")
        return
    db.upsert_student(conn, message.from_user.id, name=name, status="testing")
    await state.update_data(qidx=0, answers=[], last_question=_question_text(0))
    await state.set_state(Registration.test_question)
    await message.answer("Начинаем тест: 20 вопросов + 1 голосовой ответ.")
    await message.answer(_question_text(0))


@router.message(Registration.test_question)
async def handle_answer(message, state: FSMContext, conn):
    data = await state.get_data()
    try:
        choice = int(message.text.strip())
        if not 0 <= choice <= 3:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Ответь числом 0–3:")
        return
    answers = data["answers"] + [choice]
    qidx = data["qidx"] + 1
    if qidx < len(placement.QUESTIONS):
        await state.update_data(qidx=qidx, answers=answers, last_question=_question_text(qidx))
        await message.answer(_question_text(qidx))
        return
    voice_text = "🎤 Голосовой ответ: расскажи о своём дне — не меньше 5 предложений."
    await state.update_data(answers=answers, last_question=voice_text)
    await state.set_state(Registration.waiting_voice)
    await message.answer("Письменная часть готова! " + voice_text)


@router.message(Registration.waiting_voice)
async def handle_voice_test(message, state: FSMContext, conn, llm, admin_id, bot):
    from english_tutor.handlers.voice import save_and_transcribe
    from english_tutor.services import limits

    err = limits.check_voice(getattr(message, "voice", None))
    if err:
        await message.answer(err)
        return
    data = await state.get_data()
    transcript = await save_and_transcribe(message, bot, llm)
    limits.register_llm_call(conn, message.from_user.id)
    hint = placement.classify_voice(transcript, llm)
    score = placement.score_written(data["answers"])
    suggested = placement.suggest_level(score, hint)
    db.save_test_result(conn, message.from_user.id, score, transcript, suggested)
    db.set_student_status(conn, message.from_user.id, "pending")
    await state.clear()
    await message.answer("Спасибо! Тест отправлен на проверку — скоро открою доступ.")
    await bot.send_message(
        admin_id,
        f"Новый студент: {message.from_user.id}\nПисьменная часть: {score}/20\n"
        f"Голос (расшифровка): {transcript[:300]}\nРекомендуемый уровень: {suggested}\n"
        f"Подтверди: /approve {message.from_user.id} [{suggested}]",
    )
