from difflib import SequenceMatcher

from english_tutor.llm.prompts import STORY_SYSTEM_PROMPT, build_story_user_prompt
from english_tutor.services.exercises import normalize


class StoryFormatError(Exception):
    pass


_REQUIRED_KEYS = {
    "title",
    "text_en",
    "glossary",
    "comprehension_questions",
    "retell_prompt",
    "target_chunk",
}


def parse_story(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise StoryFormatError("Story must be a JSON dictionary")

    missing = _REQUIRED_KEYS - set(raw.keys())
    if missing:
        raise StoryFormatError(f"Missing required fields: {missing}")

    if not isinstance(raw["title"], str) or not raw["title"].strip():
        raise StoryFormatError("Field 'title' must be a non-empty string")

    if not isinstance(raw["text_en"], str) or not raw["text_en"].strip():
        raise StoryFormatError("Field 'text_en' must be a non-empty string")

    glossary = raw["glossary"]
    if not isinstance(glossary, list) or len(glossary) < 1:
        raise StoryFormatError("Field 'glossary' must be a non-empty list")
    for item in glossary:
        if not isinstance(item, dict) or "en" not in item or "ru" not in item:
            raise StoryFormatError("Each glossary item must have 'en' and 'ru'")

    questions = raw["comprehension_questions"]
    if not isinstance(questions, list) or len(questions) != 2:
        raise StoryFormatError("Must have exactly 2 comprehension questions")
    for q in questions:
        if not isinstance(q, dict) or not {"q", "options", "answer", "hint_ru"} <= set(q.keys()):
            raise StoryFormatError("Invalid question format")
        if not isinstance(q["options"], list) or len(q["options"]) != 2:
            raise StoryFormatError("Each question must have 2 options")

    if not isinstance(raw["retell_prompt"], str) or not raw["retell_prompt"].strip():
        raise StoryFormatError("Field 'retell_prompt' must be a non-empty string")

    if not isinstance(raw["target_chunk"], str) or not raw["target_chunk"].strip():
        raise StoryFormatError("Field 'target_chunk' must be a non-empty string")

    return raw


def format_story(story: dict) -> str:
    lines = [
        f"📖 **{story['title']}**",
        "",
        story["text_en"],
        "",
        "💡 **Мини-глоссарий:**",
    ]
    for item in story["glossary"]:
        lines.append(f"• **{item['en']}** — {item['ru']}")

    q1 = story["comprehension_questions"][0]
    lines.extend([
        "",
        "❓ **Проверка понимания (Вопрос 1/2):**",
        q1["q"],
        "",
        "\n".join(q1["options"]),
        "",
        "👉 Ответь числом 1 или 2:",
    ])
    return "\n".join(lines)


def get_recycling_words(conn, student_id: int, limit: int = 3) -> list[str]:
    words = []
    # 1. Take up to 2 due or existing cards from SRS
    cards = conn.execute(
        "SELECT word_en FROM srs_cards WHERE student_id=? ORDER BY due_date ASC LIMIT 2",
        (student_id,),
    ).fetchall()
    for row in cards:
        w = row["word_en"].strip()
        if w and w not in words:
            words.append(w)

    # 2. Take recent corrections
    remaining = limit - len(words)
    if remaining > 0:
        corrections = conn.execute(
            "SELECT right FROM corrections WHERE student_id=? ORDER BY created_at DESC LIMIT ?",
            (student_id, remaining),
        ).fetchall()
        for row in corrections:
            w = row["right"].strip()
            if w and w not in words:
                words.append(w)

    return words[:limit]


def _words_match(a: str, b: str) -> bool:
    if a == b:
        return True
    # tolerate inflected forms learners naturally use in retells
    # (ran/run, bought/buy) while staying strict on short words
    if len(a) < 3 or len(b) < 3:
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.6


def evaluate_retell(target_chunk: str, transcript: str) -> dict:
    norm_chunk = normalize(target_chunk).replace("*", "")
    norm_transcript = normalize(transcript).replace("*", "")
    transcript_words = norm_transcript.split()

    # Check full chunk or significant words (len >= 3)
    chunk_words = [w for w in norm_chunk.split() if len(w) >= 3]
    passed = False
    if norm_chunk in norm_transcript:
        passed = True
    elif chunk_words and all(
        any(_words_match(cw, tw) for tw in transcript_words) for cw in chunk_words
    ):
        passed = True

    if passed:
        feedback = f"✅ Отличный пересказ! Ты успешно использовал фразу «{target_chunk}»."
    else:
        feedback = (
            f"👏 Хорошая попытка пересказа, но фраза «{target_chunk}» не прозвучала.\n"
            f"Попробуй ещё раз использовать её в речи!"
        )

    return {"passed": passed, "feedback": feedback}


async def generate_story_async(conn, llm, level: str, topic: str, student_id: int) -> dict:
    recycled = get_recycling_words(conn, student_id)
    user_prompt = build_story_user_prompt(level, topic, recycled)
    raw = await llm.chat_json_async(STORY_SYSTEM_PROMPT, user_prompt)
    story = parse_story(raw)
    return story
