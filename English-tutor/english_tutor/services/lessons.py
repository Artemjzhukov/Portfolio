import json

from english_tutor.llm.prompts import LESSON_SYSTEM_PROMPT, build_lesson_user_prompt


class LessonFormatError(Exception):
    pass


_EXERCISE_KEYS = {"type", "prompt", "answer", "hint_ru"}


def parse_lesson(raw: dict) -> dict:
    for key in ("title", "explanation_ru", "exercises", "voice_task", "vocab"):
        if key not in raw:
            raise LessonFormatError(f"missing key: {key}")
    if not 3 <= len(raw["exercises"]) <= 5:
        raise LessonFormatError("exercises must be 3-5 items")
    for ex in raw["exercises"]:
        if not _EXERCISE_KEYS <= set(ex) or ex["type"] not in {"fill_in", "translate"}:
            raise LessonFormatError(f"bad exercise: {ex}")
    for word in raw["vocab"]:
        if "en" not in word or "ru" not in word:
            raise LessonFormatError(f"bad vocab entry: {word}")
    return raw


def build_prompt(level: str, topic: str) -> tuple[str, str]:
    return LESSON_SYSTEM_PROMPT, build_lesson_user_prompt(level, topic)


def _cached(conn, level, topic, kind, student_id):
    row = conn.execute(
        "SELECT content_json FROM lessons WHERE kind=? AND level=? AND topic=? "
        "AND student_id IS ?",
        (kind, level, topic, student_id),
    ).fetchone()
    return json.loads(row["content_json"]) if row else None


def _store(conn, level, topic, kind, student_id, lesson: dict):
    conn.execute(
        "INSERT INTO lessons (kind, level, topic, student_id, content_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (kind, level, topic, student_id, json.dumps(lesson, ensure_ascii=False)),
    )
    conn.commit()


def get_or_create_lesson(conn, llm, *, level: str, topic: str, kind: str,
                         student_id: int | None = None) -> dict:
    cached = _cached(conn, level, topic, kind, student_id)
    if cached is not None:
        return cached
    lesson = parse_lesson(llm.chat_json(*build_prompt(level, topic)))
    _store(conn, level, topic, kind, student_id, lesson)
    return lesson


def format_lesson(lesson: dict) -> str:
    lines = [f"📖 {lesson['title']}", "", "📚 Объяснение:", lesson["explanation_ru"], "",
             "✏️ Упражнения (пиши ответ текстом или голосом):"]
    for i, ex in enumerate(lesson["exercises"], 1):
        lines.append(f"{i}. {ex['prompt']}")
    lines += ["", "🎤 Голосовое задание:", lesson["voice_task"]]
    return "\n".join(lines)


DRILL_PROMPTS = [
    "Опиши свой день в 3 предложениях",
    "Расскажи о своём последнем выходном",
    "Опиши, что ты видишь вокруг себя прямо сейчас",
]


def format_drill_prompt(topic: str) -> str:
    return f"🎤 Speaking drill: {topic}"
