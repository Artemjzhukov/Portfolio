import re

_KEEP = re.compile(r"[^\w\s']")
_MARKDOWN = re.compile(r"[*_`~]")

_CONTRACTIONS = {
    "didn't": "did not",
    "doesn't": "does not",
    "don't": "do not",
    "can't": "cannot",
    "won't": "will not",
    "isn't": "is not",
    "aren't": "are not",
    "wasn't": "was not",
    "weren't": "were not",
    "hasn't": "has not",
    "haven't": "have not",
    "hadn't": "had not",
    "couldn't": "could not",
    "shouldn't": "should not",
    "wouldn't": "would not",
    "i'm": "i am",
    "you're": "you are",
    "we're": "we are",
    "they're": "they are",
    "he's": "he is",
    "she's": "she is",
    "it's": "it is",
    "i've": "i have",
    "you've": "you have",
    "we've": "we have",
    "they've": "they have",
    "i'll": "i will",
    "you'll": "you will",
    "he'll": "he will",
    "she'll": "she will",
    "we'll": "we will",
    "they'll": "they will",
    "i'd": "i would",
    "you'd": "you would",
    "he'd": "he would",
    "she'd": "she would",
    "we'd": "we would",
    "they'd": "they would",
}

_PAREN_HINT = re.compile(r"\([^)]*\)")
_GAP = re.compile(r"_{2,}")


def normalize(text: str | None) -> str:
    if not text:
        return ""
    text = text.lower().strip()
    text = _MARKDOWN.sub("", text)
    words = text.split()
    expanded = [_CONTRACTIONS.get(w, w) for w in words]
    text = " ".join(expanded)
    text = _KEEP.sub("", text)
    return " ".join(text.split())


def check_answer(exercise: dict, given: str) -> bool:
    target_answer = exercise.get("answer", "")
    accepted = {normalize(target_answer)}
    for alt in exercise.get("accept", []):
        accepted.add(normalize(alt))

    # Smart tolerance for fill_in: allow answering with the full reconstructed sentence
    if exercise.get("type") == "fill_in" and "prompt" in exercise:
        prompt = exercise["prompt"]
        # Remove parenthetical cues like (not / like) from prompt before filling gap
        clean_prompt = _PAREN_HINT.sub("", prompt)
        clean_prompt = " ".join(clean_prompt.split())

        # If prompt has gap ___
        if _GAP.search(clean_prompt):
            for ans in [target_answer, *exercise.get("accept", [])]:
                reconstructed = _GAP.sub(ans, clean_prompt)
                accepted.add(normalize(reconstructed))

    return normalize(given) in accepted

