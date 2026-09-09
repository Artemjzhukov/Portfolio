import re

_KEEP = re.compile(r"[^\w\s']")


def normalize(text: str | None) -> str:
    if not text:
        return ""
    text = text.lower().strip()
    text = _KEEP.sub("", text)
    return " ".join(text.split())


def check_answer(exercise: dict, given: str) -> bool:
    accepted = {normalize(exercise["answer"]), *(normalize(a) for a in exercise.get("accept", []))}
    return normalize(given) in accepted
