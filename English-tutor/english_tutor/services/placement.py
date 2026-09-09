import importlib.resources
import json

_LEVELS = ["A2", "B1", "B2"]
_BANDS = {"A2": (6, 11), "B1": (12, 16), "B2": (17, 20)}


def _load() -> list[dict]:
    data = importlib.resources.files("english_tutor").joinpath("data/placement_questions.json")
    return json.loads(data.read_text(encoding="utf-8"))


QUESTIONS = _load()


def score_written(answers: list[int | None]) -> int:
    return sum(1 for q, a in zip(QUESTIONS, answers) if a is not None and a == q["answer"])


def suggest_level(score: int, voice_hint: str | None = None) -> str:
    level = next(name for name, (lo, hi) in _BANDS.items() if lo <= score <= hi)
    if voice_hint in _LEVELS and voice_hint != level:
        d = _LEVELS.index(voice_hint) - _LEVELS.index(level)
        if abs(d) == 1:
            lo, _hi = _BANDS[level]
            near_lower_boundary = score <= lo
            next_lower = _BANDS[_LEVELS[_LEVELS.index(level) + d]][0]
            near_upper_boundary = score >= next_lower - 1
            if (d > 0 and near_upper_boundary) or (d < 0 and near_lower_boundary):
                return voice_hint
    return level


def classify_voice(transcript: str, llm) -> str | None:
    from english_tutor.llm.prompts import VOICE_LEVEL_PROMPT

    try:
        raw = llm.chat_json(VOICE_LEVEL_PROMPT, transcript)
    except Exception:
        return None
    level = raw.get("level") if isinstance(raw, dict) else None
    return level if level in _LEVELS else None
