CHAT_SYSTEM_PROMPT_TEMPLATE = (
    "You are a friendly English conversation partner for a Russian-speaking learner "
    "at CEFR level {level}. Reply in natural English suited to that level. "
    "When the learner makes a grammar or vocabulary mistake, list each one in 'corrections'. "
    'Reply ONLY with JSON: {{"reply": str, "corrections": '
    '[{{"wrong": str, "right": str, "hint_ru": str}}]}}. '
    "corrections may be an empty list. 'hint_ru' is a short explanation in Russian."
)


def chat_system_prompt(level: str) -> str:
    return CHAT_SYSTEM_PROMPT_TEMPLATE.format(level=level)


class ChatFormatError(Exception):
    pass


def parse_chat(raw: dict) -> dict:
    if not isinstance(raw, dict) or "reply" not in raw or "corrections" not in raw:
        raise ChatFormatError("missing reply/corrections")
    if not isinstance(raw["reply"], str) or not raw["reply"].strip():
        raise ChatFormatError("reply must be a non-empty string")
    if not isinstance(raw["corrections"], list):
        raise ChatFormatError("corrections must be a list")
    for c in raw["corrections"]:
        if not isinstance(c, dict) or set(c) != {"wrong", "right", "hint_ru"}:
            raise ChatFormatError(f"bad correction: {c}")
        if not all(isinstance(v, str) and v.strip() for v in c.values()):
            raise ChatFormatError(f"bad correction values: {c}")
    return raw


def format_chat_answer(data: dict) -> str:
    text = data["reply"]
    corrections = data.get("corrections") or []
    if not corrections:
        return text + "\n\n(ошибок нет 👍)"
    lines = ["📝 Исправления:"]
    for c in corrections:
        lines.append(f"• «{c['wrong']}» → «{c['right']}» ({c['hint_ru']})")
    return text + "\n\n" + "\n".join(lines)
