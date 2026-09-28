from english_tutor.services.exercises import check_answer, normalize
from english_tutor.services.lessons import format_drill_prompt, format_exercise_prompt, format_lesson
from tests.test_lessons import RAW


def test_format_lesson_includes_all_parts():
    text = format_lesson(RAW)
    assert "📖 Past Simple" in text and "📚 Объяснение:" in text
    assert "🎯 Программа тренировки:" in text
    assert "1. [choice] Выбери правильный вариант" in text
    assert "🎤 Финальное задание на говорение:" in text
    assert "Расскажи о своём самом продуктивном" in text
    assert "Задание 1:" in text


def test_format_exercise_prompt():
    ex = RAW["exercises"][1]
    res = format_exercise_prompt(ex, 2)
    assert "Задание 2:" in res
    assert "👉 Напиши только пропущенное слово" in res
    assert "I ___ (go) home yesterday." in res


def test_format_drill_prompt():
    assert format_drill_prompt("Мой день").startswith("🎤")


def test_normalize_handles_none():
    assert normalize(None) == ""


def test_check_answer_handles_none():
    ex = {"type": "fill_in", "prompt": "I ___ home.", "answer": "went"}
    assert check_answer(ex, None) is False


