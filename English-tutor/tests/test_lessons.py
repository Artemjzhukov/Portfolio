import pytest

from english_tutor.services import lessons

RAW = {
    "title": "Past Simple",
    "explanation_ru": "Прошедшее время используется для событий, завершенных в прошлом...",
    "exercises": [
        {
            "type": "choice",
            "instruction_ru": "Выбери правильный вариант (ответь 1 или 2):",
            "prompt": (
                "Когда мы используем Past Simple?\n"
                "1. Действие произошло в точное время в прошлом\n"
                "2. Действие связано с настоящим"
            ),
            "answer": "1",
            "accept": ["1."],
            "hint_ru": "Past Simple требует привязки к прошлому (yesterday, ago)",
        },
        {
            "type": "fill_in",
            "instruction_ru": "Напиши только пропущенное слово в нужной форме:",
            "prompt": "I ___ (go) home yesterday.",
            "answer": "went",
            "accept": [],
            "hint_ru": "неправильный глагол go -> went",
        },
        {
            "type": "fill_in",
            "instruction_ru": "Напиши только пропущенное слово в нужной форме:",
            "prompt": "We ___ (not / see) him last week.",
            "answer": "didn't see",
            "accept": ["did not see"],
            "hint_ru": "отрицание в прошлом: didn't + V1",
        },
        {
            "type": "translate",
            "instruction_ru": "Напиши перевод предложения целиком (или наговори голосом):",
            "prompt": "Переведи: 'Она купила хлеб вчера.'",
            "answer": "She bought bread yesterday",
            "accept": [],
            "hint_ru": "buy -> bought",
        },
        {
            "type": "translate",
            "instruction_ru": "Напиши перевод предложения целиком (или наговори голосом):",
            "prompt": "Переведи: 'Я вчера застрял в пробке.'",
            "answer": "I got stuck in traffic yesterday",
            "accept": ["I was stuck in traffic yesterday"],
            "hint_ru": "застрять в пробке = get stuck in traffic",
        },
        {
            "type": "shadowing",
            "instruction_ru": "Повтори эталонную фразу вслух (нажми микрофон 🎤):",
            "prompt": "We had a great time two days ago.",
            "answer": "We had a great time two days ago",
            "accept": [],
            "hint_ru": "произноси связно: had-a great time",
        },
    ],
    "voice_task": "Расскажи о своём самом продуктивном или странном дне на прошлой неделе.",
    "vocab": [{"en": f"chunk {i}", "ru": f"фраза {i}"} for i in range(1, 9)],
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
    lesson = lessons.parse_lesson(RAW)
    assert lesson["title"] == "Past Simple"
    assert len(lesson["exercises"]) == 6
    assert all("instruction_ru" in ex for ex in lesson["exercises"])


def test_parse_lesson_requires_instruction_ru():
    bad = {
        **RAW,
        "exercises": [
            {k: v for k, v in RAW["exercises"][0].items() if k != "instruction_ru"},
            *RAW["exercises"][1:],
        ],
    }
    with pytest.raises(lessons.LessonFormatError):
        lessons.parse_lesson(bad)


def test_parse_lesson_supports_all_phase_types():
    # choice, fill_in, translate, shadowing
    types = [ex["type"] for ex in RAW["exercises"]]
    assert set(types) == {"choice", "fill_in", "translate", "shadowing"}


def test_parse_lesson_rejects_too_few_exercises():
    bad = {**RAW, "exercises": RAW["exercises"][:4]}
    with pytest.raises(lessons.LessonFormatError):
        lessons.parse_lesson(bad)


def test_parse_lesson_rejects_too_many_exercises():
    bad = {**RAW, "exercises": [*RAW["exercises"], RAW["exercises"][0], RAW["exercises"][1]]}
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


def test_parse_lesson_rejects_wrong_vocab_length():
    bad = {**RAW, "vocab": RAW["vocab"][:1]}
    with pytest.raises(lessons.LessonFormatError):
        lessons.parse_lesson(bad)


def test_parse_lesson_rejects_wrong_types():
    bad = {**RAW, "title": 123}
    with pytest.raises(lessons.LessonFormatError):
        lessons.parse_lesson(bad)
    bad2 = {**RAW, "exercises": [{**RAW["exercises"][0], "answer": 5}]}
    with pytest.raises(lessons.LessonFormatError):
        lessons.parse_lesson(bad2)


def test_build_prompt_uses_prompts_module():
    system, user = lessons.build_prompt("B2", "Reported speech")
    assert "STRICT JSON" in system and "B2" in user and "Reported speech" in user

