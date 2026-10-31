from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def learner_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Уроки"), KeyboardButton(text="💬 Разговор")],
            [KeyboardButton(text="🔁 Повторение"), KeyboardButton(text="📄 Мой материал")],
            [KeyboardButton(text="🎯 Собеседование"), KeyboardButton(text="📊 Мой уровень")],
            [KeyboardButton(text="📈 Статистика")],
        ],
        resize_keyboard=True,
    )


def admin_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👥 Студенты"), KeyboardButton(text="➕ Инвайт")],
            [KeyboardButton(text="📊 Обзор"), KeyboardButton(text="🧑‍🎓 Режим ученика")],
        ],
        resize_keyboard=True,
    )


def material_items_keyboard(items, selected: set) -> InlineKeyboardMarkup:
    rows = []
    for it in items:
        mark = "✅" if it["id"] in selected else "⬜"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark} {it['en']}", callback_data=f"mat:toggle:{it['id']}"
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="💾 Сохранить выбранные", callback_data="mat:save")])
    rows.append([InlineKeyboardButton(text="⏭ Пропустить", callback_data="mat:skip")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def exercise_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎤 Произношение", callback_data="mat:ex:pron")],
            [InlineKeyboardButton(text="📝 Перевод", callback_data="mat:ex:trans")],
            [InlineKeyboardButton(text="✏️ Диктант", callback_data="mat:ex:dict")],
            [InlineKeyboardButton(text="✅ Завершить", callback_data="mat:ex:done")],
        ]
    )


def cancel_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="mat:cancel")]]
    )
