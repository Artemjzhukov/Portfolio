import re


def normalize_for_match(text: str) -> str:
    text = (text or "").lower()
    # Treat hyphens/dashes as spaces so phrase variants match.
    text = re.sub(r"[-–—]", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def check_pronunciation(expected: str, transcript: str) -> bool:
    return normalize_for_match(expected) == normalize_for_match(transcript)


def check_spelling(expected: str, typed: str) -> bool:
    return (expected or "").strip().lower() == (typed or "").strip().lower()


def build_exercise_queue(items, selected_ids, types=("pronunciation", "translation", "dictation")):
    selected = [it for it in items if it["id"] in set(selected_ids)]
    queue = []
    for it in selected:
        for t in types:
            queue.append({"type": t, "item": it})
    return queue
