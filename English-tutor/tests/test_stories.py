import pytest

from english_tutor.services import stories

RAW_STORY = {
    "title": "A Morning Coffee",
    "text_en": (
        "Every morning, Alex wakes up early. He likes to drink fresh coffee before work. "
        "Yesterday, he **ran out of** coffee beans. He had to go to the supermarket. "
        "Luckily, he didn't **get stuck in traffic**. He bought a new package and smiled."
    ),
    "glossary": [
        {"en": "run out of", "ru": "закончиться (о запасах)"},
        {"en": "get stuck in traffic", "ru": "застрять в пробке"},
    ],
    "comprehension_questions": [
        {
            "q": "Why did Alex go to the supermarket?",
            "options": ["1. He ran out of coffee beans", "2. He wanted to buy milk"],
            "answer": "1",
            "hint_ru": "Обрати внимание: he ran out of coffee beans",
        },
        {
            "q": "Did Alex get stuck in traffic yesterday?",
            "options": ["1. Yes, he did", "2. No, he didn't"],
            "answer": "2",
            "hint_ru": "В тексте: Luckily, he didn't get stuck in traffic",
        },
    ],
    "retell_prompt": (
        "Перескажи сюжет истории своими словами за 3–4 предложения. "
        "Обязательно используй фразу 'run out of' или 'get stuck in traffic'."
    ),
    "target_chunk": "run out of",
}


def test_parse_story_valid():
    story = stories.parse_story(RAW_STORY)
    assert story["title"] == "A Morning Coffee"
    assert len(story["comprehension_questions"]) == 2
    assert len(story["glossary"]) == 2


def test_parse_story_missing_field():
    bad = {k: v for k, v in RAW_STORY.items() if k != "target_chunk"}
    with pytest.raises(stories.StoryFormatError):
        stories.parse_story(bad)


def test_parse_story_invalid_questions_count():
    bad = {**RAW_STORY, "comprehension_questions": RAW_STORY["comprehension_questions"][:1]}
    with pytest.raises(stories.StoryFormatError):
        stories.parse_story(bad)


def test_format_story():
    formatted = stories.format_story(RAW_STORY)
    assert "📖 **A Morning Coffee**" in formatted
    assert "ran out of" in formatted
    assert "💡 **Мини-глоссарий:**" in formatted
    assert "1/2" in formatted


def test_get_recycling_words_empty_when_no_data(conn):
    words = stories.get_recycling_words(conn, 42)
    assert words == []


def test_get_recycling_words_from_cards_and_corrections(conn):
    from english_tutor import db
    from english_tutor.services import srs

    db.upsert_student(conn, 42, status="active", level="A2")
    srs.ensure_card(conn, 42, "hurry up", "поторопись")
    db.insert_correction(conn, 42, "I go", "I went", "past simple", source="chat")

    words = stories.get_recycling_words(conn, 42)
    assert len(words) >= 1
    assert any("hurry up" in w or "went" in w for w in words)


def test_evaluate_retell_success():
    eval_res = stories.evaluate_retell(
        target_chunk="run out of",
        transcript="Alex woke up and he ran out of coffee so he bought it in the shop.",
    )
    assert eval_res["passed"] is True
    assert "✅" in eval_res["feedback"]


def test_evaluate_retell_missing_target_chunk():
    eval_res = stories.evaluate_retell(
        target_chunk="run out of",
        transcript="Alex went to the supermarket and bought some coffee yesterday.",
    )
    assert eval_res["passed"] is False
    assert "run out of" in eval_res["feedback"]
