from aiogram import F, Router
from aiogram.fsm.context import FSMContext

from english_tutor import db
from english_tutor.handlers import admin, chat, lessons, materials, review
from english_tutor.utils.keyboards import learner_main_keyboard

router = Router()


@router.message(F.text == "📚 Уроки")
async def btn_lessons(message, state: FSMContext, conn):
    await state.clear()
    await lessons.lessons_cmd(message, state, conn)


@router.message(F.text == "💬 Разговор")
async def btn_chat(message, state: FSMContext, conn):
    await state.clear()
    await chat.chat_cmd(message, state, conn)


@router.message(F.text == "🔁 Повторение")
async def btn_review(message, state: FSMContext, conn):
    await state.clear()
    await review.review_cmd(message, state, conn)


@router.message(F.text == "📄 Мой материал")
async def btn_material(message, state: FSMContext, conn):
    await state.clear()
    mats = db.list_materials(conn, message.from_user.id)
    if mats:
        await materials.materials_library_cmd(message, state, conn)
    else:
        await materials.material_cmd(message, state, conn)
        await message.answer("Материалов пока нет. Начни импорт текста выше.")


@router.message(F.text == "🎯 Собеседование")
async def btn_interview(message, state: FSMContext, conn):
    await state.clear()
    await lessons.lessons_cmd(message, state, conn)
    await message.answer("Напиши тему «собеседование» или выбери номер.")


@router.message(F.text == "📊 Мой уровень")
async def btn_level(message, state: FSMContext, conn):
    await state.clear()
    await lessons.mylevel_cmd(message, state, conn)


@router.message(F.text == "📈 Статистика")
async def btn_stats(message, state: FSMContext, conn):
    await state.clear()
    await lessons.mylevel_cmd(message, state, conn)


@router.message(F.text == "👥 Студенты")
async def btn_students(message, state: FSMContext, conn, admin_id):
    await state.clear()
    if not admin._is_admin(message, admin_id):
        await message.answer("Эта команда только для админа.")
        return
    await admin.students(message, conn, admin_id)


@router.message(F.text == "➕ Инвайт")
async def btn_invite(message, state: FSMContext, conn, admin_id):
    await state.clear()
    if not admin._is_admin(message, admin_id):
        await message.answer("Эта команда только для админа.")
        return
    await admin.invite(message, conn, admin_id)


@router.message(F.text == "📊 Обзор")
async def btn_overview(message, state: FSMContext, conn, admin_id, llm):
    await state.clear()
    if not admin._is_admin(message, admin_id):
        await message.answer("Эта команда только для админа.")
        return
    await admin.stats_cmd(message, conn, llm, admin_id)


@router.message(F.text == "🧑‍🎓 Режим ученика")
async def btn_student_mode(message, state: FSMContext):
    await state.clear()
    await message.answer("Режим ученика.", reply_markup=learner_main_keyboard())
