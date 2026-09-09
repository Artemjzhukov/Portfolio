import pytest

from english_tutor.services import lessons

RAW = {
    "title": "Past Simple",
    "explanation_ru": "Прошедшее время...",
    "exercises": [
        {"type": "fill_in", "prompt": "I ___ home.", "answer": "went",
         "accept": [], "hint_ru": "неправильный глагол"},
        {"type": "translate", "prompt": "Она купила хлеб.", "answer": "she bought bread",
         "accept": [], "hint_ru": "buy → bought"},
        {"type": "fill_in", "prompt": "We ___ TV last night.", "answer": "watched",
         "accept": [], "hint_ru": "правильный глагол"},
    ],
    "voice_task": "Расскажи, что ты делал(а) вчера",
    "vocab": [{"en": "yesterday", "ru": "вчера"}, {"en": "ago", "ru": "тому назад"}],
}


class FakeLLM:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def chat_json(self, system, user):
        self.calls += 1
        return self.reply


@pytest.fixture
def llm():
    return FakeLLM(RAW)


def test_parse_lesson_ok(llm):
    assert lessons.parse_lesson(RAW)["title"] == "Past Simple"


def test_parse_lesson_rejects_too_few_exercises():
    bad = {**RAW, "exercises": RAW["exercises"][:2]}
    with pytest.raises(lessons.LessonFormatError):
        lessons.parse_lesson(bad)


def test_parse_lesson_rejects_missing_key():
    bad2 = {k: v for k, v in RAW.items() if k != "voice_task"}
    with pytest.raises(lessons.LessonFormatError):
        lessons.parse_lesson(bad2)


def test_get_or_create_generates_then_caches(conn, llm):
    a = lessons.get_or_create_lesson(conn, llm, level="A2", topic="Past Simple", kind="curriculum")
    b = lessons.get_or_create_lesson(conn, llm, level="A2", topic="Past Simple", kind="curriculum")
    assert a == RAW and b == RAW
    assert llm.calls == 1


def test_theme_lessons_cached_per_student(conn, llm):
    from english_tutor import db

    db.upsert_student(conn, 1)
    db.upsert_student(conn, 2)
    lessons.get_or_create_lesson(conn, llm, level="B1", topic="cooking", kind="theme", student_id=1)
    lessons.get_or_create_lesson(conn, llm, level="B1", topic="cooking", kind="theme", student_id=2)
    assert llm.calls == 2


def test_build_prompt_uses_prompts_module():
    system, user = lessons.build_prompt("B2", "Reported speech")
    assert "STRICT JSON" in system and "B2" in user and "Reported speech" in user
