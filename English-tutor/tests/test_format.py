from english_tutor.services.exercises import check_answer, normalize
from english_tutor.services.lessons import format_drill_prompt, format_lesson
from tests.test_lessons import RAW


def test_format_lesson_includes_all_parts():
    text = format_lesson(RAW)
    assert "📖 Past Simple" in text and "📚 Объяснение:" in text
    assert "1. I ___ home." in text and "🎤 Голосовое задание:" in text
    assert "Расскажи, что ты делал(а) вчера" in text


def test_format_drill_prompt():
    assert format_drill_prompt("Мой день").startswith("🎤")


def test_normalize_handles_none():
    assert normalize(None) == ""


def test_check_answer_handles_none():
    ex = {"type": "fill_in", "prompt": "I ___ home.", "answer": "went"}
    assert check_answer(ex, None) is False

