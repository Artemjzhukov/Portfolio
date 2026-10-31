import json

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from english_tutor import db
from english_tutor.services import lessons, limits, material_exercises, srs
from english_tutor.utils.keyboards import (
    exercise_menu_keyboard,
    material_items_keyboard,
)

router = Router()


class MaterialSession(StatesGroup):
    waiting_text = State()
    selecting = State()
    exercising = State()


class MaterialsLibrary(StatesGroup):
    listing = State()


def _guard(message_or_cb, conn):
    student = db.get_student(conn, message_or_cb.from_user.id)
    return student if student and student["status"] == "active" else None

@router.message(Command("material", "mymaterial"))
async def material_cmd(message: Message, state: FSMContext, conn):
    student = _guard(message, conn)
    if student is None:
        await message.answer("Сначала нужно пройти тест: /start")
        return
    await state.set_state(MaterialSession.waiting_text)
    await state.update_data(student_level=student["level"])
    await message.answer(
        "Отправь текст (до 6000 символов) или голосовое с отрывком/статьёй.\n"
        "Я разберу фразы, термины и слова, а ты выберешь, что сохранить.\n"
        "Отмена — кнопка ниже или /cancel.",
    )


@router.message(Command("materials"))
async def materials_library_cmd(message: Message, state: FSMContext, conn):
    student = _guard(message, conn)
    if student is None:
        await message.answer("Сначала нужно пройти тест: /start")
        return
    mats = db.list_materials(conn, message.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить материал", callback_data="matlib:add")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="matlib:cancel")],
    ])
    if not mats:
        await message.answer("У тебя пока нет сохранённых материалов.", reply_markup=kb)
        return
    lines = ["Твои материалы:"]
    for i, m in enumerate(mats, 1):
        title = m["title"] or "Без названия"
        lines.append(f"{i}. {title}")
    await state.set_state(MaterialsLibrary.listing)
    await state.update_data(material_ids=[m["id"] for m in mats])
    await message.answer("\n".join(lines) + "\n\nОтправь номер, чтобы открыть.", reply_markup=kb)
    await message.answer("Отмена: /cancel")


@router.callback_query(lambda c: c.data == "matlib:add")
async def cb_matlib_add(cb: CallbackQuery, state: FSMContext, conn):
    student = _guard(cb, conn)
    if student is None:
        await cb.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(MaterialSession.waiting_text)
    await state.update_data(student_level=student["level"])
    await cb.message.answer("Otprav tekst ili golosovoe.")
    await cb.answer()


@router.callback_query(lambda c: c.data == "matlib:cancel")
async def cb_matlib_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("Отменено.")
    await cb.answer()

@router.message(MaterialsLibrary.listing)
async def materials_library_select(message: Message, state: FSMContext, conn):
    data = await state.get_data()
    ids = data.get("material_ids", [])
    text = (message.text or "").strip()
    if not text.isdigit() or not (1 <= int(text) <= len(ids)):
        await message.answer("Отправь номер из списка.")
        return
    mid = ids[int(text) - 1]
    mat = db.get_material(conn, mid)
    if mat is None or mat["student_id"] != message.from_user.id:
        await message.answer("Материал недоступен.")
        await state.clear()
        return
    analysis = json.loads(mat["analysis_json"])
    items = db.get_material_items(conn, mid)
    item_list = [{"id": r["id"], "type": r["item_type"], "en": r["en"], "ru": r["ru"]} for r in items]
    await state.clear()
    await message.answer(f"📄 {analysis.get('title','Материал')}")
    for it in item_list:
        await message.answer(f"- {it['en']} — {it['ru']}")
    await message.answer("Повторение по материалу: /reviewmaterial\nНовый импорт: /material")


@router.message(MaterialSession.waiting_text, ~F.text.startswith("/"))
async def material_text(message: Message, state: FSMContext, conn, llm):
    student = db.get_student(conn, message.from_user.id)
    if student is None:
        await state.clear()
        return
    text = None
    if message.voice is not None:
        err = limits.check_voice(message.voice)
        if err:
            await message.answer(err)
            return
        if not limits.try_reserve_llm(conn, message.from_user.id):
            await message.answer("Дневной лимит запросов исчерпан, попробуй завтра. 🌙")
            return
        from english_tutor.handlers.voice import save_and_transcribe

        try:
            text = await save_and_transcribe(message, message.bot, llm)
        except Exception:
            await message.answer("Не удалось распознать голосовое. Попробуй ещё раз.")
            return
    elif message.text:
        err = limits.check_material_text(message.text)
        if err:
            await message.answer(err)
            return
        text = message.text
    else:
        await message.answer("Отправь текст или голосовое.")
        return

    from english_tutor import db as _db
    from english_tutor.services import materials as _materials

    norm = _materials.normalize_text(text)
    h = _materials.hash_text(norm)
    cached = _db.get_material_by_hash(conn, message.from_user.id, h)
    if cached is not None:
        analysis = json.loads(cached["analysis_json"])
        material = cached
        items = _db.get_material_items(conn, material["id"])
        item_list = [{"id": r["id"], "type": r["item_type"], "en": r["en"], "ru": r["ru"]} for r in items]
        await state.set_state(MaterialSession.selecting)
        await state.update_data(material_id=material["id"], analysis=analysis, items=item_list, selected=set())
        await message.answer(_materials.format_analysis(material, analysis))
        await message.answer("Отметь элементы для сохранения:", reply_markup=material_items_keyboard(item_list, set()))
        return

    if not limits.try_reserve_material_analysis(conn, message.from_user.id):
        await message.answer("Лимит анализа материалов на сегодня исчерпан (5 попыток в день).")
        return
    if not limits.try_reserve_llm(conn, message.from_user.id):
        await message.answer("Дневной лимит запросов исчерпан, попробуй завтра. 🌙")
        return
    try:
        material, analysis, cache_hit = await _materials.get_or_analyze_material(
            conn, llm, message.from_user.id, text, level=student["level"]
        )
    except Exception:
        await message.answer("Не удалось проанализировать материал. Попробуй ещё раз или вернись в меню.")
        await state.set_state(MaterialSession.waiting_text)
        return
    items = _db.get_material_items(conn, material["id"])
    item_list = [{"id": r["id"], "type": r["item_type"], "en": r["en"], "ru": r["ru"]} for r in items]
    await state.set_state(MaterialSession.selecting)
    await state.update_data(material_id=material["id"], analysis=analysis, items=item_list, selected=set())
    await message.answer(_materials.format_analysis(material, analysis))
    await message.answer("Отметь элементы для сохранения:", reply_markup=material_items_keyboard(item_list, set()))

@router.callback_query(lambda c: c.data and c.data.startswith("mat:toggle:"))
async def cb_toggle(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = set(data.get("selected", set()))
    item_id = int(cb.data.split(":")[-1])
    if item_id in selected:
        selected.discard(item_id)
    else:
        selected.add(item_id)
    await state.update_data(selected=selected)
    items = data.get("items", [])
    await cb.message.edit_reply_markup(reply_markup=material_items_keyboard(items, selected))
    await cb.answer()


@router.callback_query(lambda c: c.data == "mat:save")
async def cb_save(cb: CallbackQuery, state: FSMContext, conn):
    data = await state.get_data()
    selected = data.get("selected", set())
    items = data.get("items", [])
    material_id = data.get("material_id")
    saved = 0
    for it in items:
        if it["id"] in selected:
            srs.ensure_card(conn, cb.from_user.id, it["en"], it["ru"], material_id=material_id)
            saved += 1
    await state.set_state(MaterialSession.exercising)
    await state.update_data(exercise_queue=[])
    await cb.message.answer(f"Сохранено карточек: {saved}.")
    await cb.message.answer("Выбери упражнение:", reply_markup=exercise_menu_keyboard())
    await cb.answer()


@router.callback_query(lambda c: c.data == "mat:skip")
async def cb_skip(cb: CallbackQuery, state: FSMContext):
    await state.set_state(MaterialSession.exercising)
    await state.update_data(exercise_queue=[])
    await cb.message.answer(
        "Ок, ничего не сохранено. Выбери упражнение:", reply_markup=exercise_menu_keyboard()
    )
    await cb.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("mat:ex:"))
async def cb_exercise(cb: CallbackQuery, state: FSMContext, conn):
    action = cb.data.split(":")[-1]
    data = await state.get_data()
    if action == "done":
        analysis = data.get("analysis", {})
        title = analysis.get("title", "material")
        student = db.get_student(conn, cb.from_user.id)
        lesson_id = lessons.find_lesson_id(conn, "material", student["level"], title, student["tg_id"])
        if lesson_id is None:
            cur = conn.execute(
                "INSERT INTO lessons (kind, level, topic, student_id, content_json) VALUES (?,?,?,?,?)",
                (
                    "material",
                    student["level"],
                    title,
                    student["tg_id"],
                    json.dumps(analysis, ensure_ascii=False),
                ),
            )
            conn.commit()
            lesson_id = cur.lastrowid
        db.record_progress(conn, cb.from_user.id, lesson_id, "completed", data.get("correct", 0))
        await state.clear()
        await cb.message.answer(
            f"Готово! Верно: {data.get('correct',0)}/{len(queue)}.\n"
            "Дальше: /review — повторение, /materials — мои материалы, /material — новый импорт, /lessons — уроки."
        )
        await cb.answer()
        return
    items = data.get("items", [])
    selected = data.get("selected", set())
    queue = material_exercises.build_exercise_queue(items, selected)
    if not queue:
        await cb.message.answer("Нет выбранных элементов. Сначала сохрани элементы.")
        await cb.answer()
        return
    await state.update_data(exercise_queue=queue, ex_idx=0, correct=0)
    await _send_next_exercise(cb.message, state)
    await cb.answer()


async def _send_next_exercise(message, state: FSMContext):
    data = await state.get_data()
    queue = data.get("exercise_queue", [])
    idx = data.get("ex_idx", 0)
    if idx >= len(queue):
        await message.answer(
            "Упражнения завершены. Выбери ещё или «Завершить».",
            reply_markup=exercise_menu_keyboard(),
        )
        return
    ex = queue[idx]
    item = ex["item"]
    t = ex["type"]
    if t == "pronunciation":
        await message.answer(f"🎤 Произнеси вслух: {item['en']} ({item['ru']})\nОтправь голосовое.")
    elif t == "translation":
        await message.answer(f"Переведи на английский: {item['ru']}")
    else:
        await message.answer(f"Напиши слово по-английски: {item['ru']}")


@router.message(MaterialSession.exercising, ~F.text.startswith("/"))
async def material_exercise_flow(message: Message, state: FSMContext, conn, llm):
    data = await state.get_data()
    queue = data.get("exercise_queue", [])
    idx = data.get("ex_idx", 0)
    if idx >= len(queue):
        await message.answer("Выбери упражнение:", reply_markup=exercise_menu_keyboard())
        return
    ex = queue[idx]
    item = ex["item"]
    t = ex["type"]
    ok = False
    skip = False
    if t == "pronunciation":
        if message.voice is None:
            await message.answer("Жду голосовое 🎤")
            return
        err = limits.check_voice(message.voice)
        if err:
            await message.answer(err)
            return
        if not limits.can_use_llm(conn, message.from_user.id):
            await message.answer("Лимит исчерпан.")
            return
        limits.register_llm_call(conn, message.from_user.id)
        from english_tutor.handlers.voice import save_and_transcribe

        transcript = await save_and_transcribe(message, message.bot, llm)
        ok = material_exercises.check_pronunciation(item["en"], transcript)
        await message.answer(f"📝 Расшифровка: {transcript}")
    elif t == "translation":
        answer = message.text or ""
        if message.voice is not None:
            if not limits.can_use_llm(conn, message.from_user.id):
                await message.answer("Лимит исчерпан.")
                return
            limits.register_llm_call(conn, message.from_user.id)
            from english_tutor.handlers.voice import save_and_transcribe

            answer = await save_and_transcribe(message, message.bot, llm)
        if (answer or "").strip().lower() in {"пропустить", "skip"}:
            await message.answer("Пропущено.")
            ok = False
            skip = True
        else:
            ok = material_exercises.normalize_for_match(answer) == material_exercises.normalize_for_match(item["en"])
            skip = False
    else:
        typed = (message.text or "").strip()
        if typed.lower() in {"пропустить", "skip"}:
            await message.answer("Пропущено.")
            ok = False
            skip = True
        else:
            ok = material_exercises.check_spelling(item["en"], typed)
            skip = False
    if skip:
        pass
    elif ok:
        await message.answer("✅ Верно!")
    else:
        await message.answer(f"❌ Правильно: {item['en']}")
    idx += 1
    await state.update_data(ex_idx=idx, correct=data.get("correct", 0) + (1 if ok else 0))
    await _send_next_exercise(message, state)


@router.callback_query(lambda c: c.data == "mat:cancel")
async def cb_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("Отменено.")
    await cb.answer()
