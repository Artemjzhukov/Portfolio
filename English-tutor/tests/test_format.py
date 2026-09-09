from english_tutor.services.lessons import format_drill_prompt, format_lesson
from tests.test_lessons import RAW


def test_format_lesson_includes_all_parts():
    text = format_lesson(RAW)
    assert "📖 Past Simple" in text and "📚 Объяснение:" in text
    assert "1. I ___ home." in text and "🎤 Голосовое задание:" in text
    assert "Расскажи, что ты делал(а) вчера" in text


def test_format_drill_prompt():
    assert format_drill_prompt("Мой день").startswith("🎤")
