import asyncio
import json

from english_tutor.llm.prompts import LESSON_SYSTEM_PROMPT, build_lesson_user_prompt


class LessonFormatError(Exception):
    pass


_EXERCISE_KEYS = {"type", "prompt", "answer", "hint_ru"}


def parse_lesson(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise LessonFormatError("lesson must be a JSON object")
    for key in ("title", "explanation_ru", "exercises", "voice_task", "vocab"):
        if key not in raw:
            raise LessonFormatError(f"missing key: {key}")
    if not isinstance(raw["title"], str) or not raw["title"].strip():
        raise LessonFormatError("title must be a non-empty string")
    if not isinstance(raw["explanation_ru"], str) or not raw["explanation_ru"].strip():
        raise LessonFormatError("explanation_ru must be a non-empty string")
    if not isinstance(raw["voice_task"], str) or not raw["voice_task"].strip():
        raise LessonFormatError("voice_task must be a non-empty string")
    exercises = raw["exercises"]
    if not isinstance(exercises, list) or not 3 <= len(exercises) <= 5:
        raise LessonFormatError("exercises must be a list of 3-5 items")
    for ex in exercises:
        if not isinstance(ex, dict) or not _EXERCISE_KEYS <= set(ex):
            raise LessonFormatError(f"bad exercise keys: {ex}")
        if ex["type"] not in {"fill_in", "translate"}:
            raise LessonFormatError(f"bad exercise type: {ex['type']}")
        for k in ("prompt", "answer", "hint_ru"):
            if not isinstance(ex[k], str) or not ex[k].strip():
                raise LessonFormatError(f"exercise.{k} must be a non-empty string")
    vocab = raw["vocab"]
    if not isinstance(vocab, list) or not 8 <= len(vocab) <= 12:
        raise LessonFormatError("vocab must be a list of 8-12 items")
    for word in vocab:
        if not isinstance(word, dict) or set(word) != {"en", "ru"}:
            raise LessonFormatError(f"bad vocab entry: {word}")
        if not all(isinstance(v, str) and v.strip() for v in word.values()):
            raise LessonFormatError(f"bad vocab entry values: {word}")
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


def find_lesson_id(conn, kind: str, level: str, topic: str, student_id: int | None) -> int | None:
    row = conn.execute(
        "SELECT id FROM lessons WHERE kind=? AND level=? AND topic=? AND student_id IS ?",
        (kind, level, topic, student_id),
    ).fetchone()
    return row["id"] if row else None


def format_drill_prompt(topic: str) -> str:
    return f"🎤 Задание на говорение: {topic}"


async def get_or_create_lesson_async(conn, llm, *, level: str, topic: str, kind: str,
                                     student_id: int | None = None) -> dict:
    cached = _cached(conn, level, topic, kind, student_id)
    if cached is not None:
        return cached
    system, user = build_prompt(level, topic)
    # DB access stays on the main thread; only the LLM call may leave it
    if hasattr(llm, "chat_json_async"):
        raw = await llm.chat_json_async(system, user)
    else:
        raw = await asyncio.to_thread(llm.chat_json, system, user)
    lesson = parse_lesson(raw)
    _store(conn, level, topic, kind, student_id, lesson)
    return lesson
