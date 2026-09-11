import logging
import os
import traceback

from aiogram import Router

router = Router()

logger = logging.getLogger("english_tutor.errors")

_LLM_MARKERS = ("LLMParseError", "groq", "RateLimit", "timeout")


def redact(text: str) -> str:
    for key in ("GROQ_API_KEY", "BOT_TOKEN"):
        value = os.environ.get(key, "")
        if value:
            text = text.replace(value, "<REDACTED>")
    return text


@router.errors()
async def on_error(event, exception: Exception):
    logger.error("unhandled error: %s\n%s", exception, redact(traceback.format_exc()))
    message = getattr(event, "message", None)
    if message is None:
        return
    name = type(exception).__name__.lower()
    msg = str(exception).lower()
    if ("llmparse" in name or "groq" in name or "ratelimit" in name or "timeout" in name
            or "groq" in msg or "ratelimit" in msg):
        await message.answer("Проблема с сервисом языка, попробуй ещё раз через минуту. 🛠")
    else:
        await message.answer("Что-то пошло не так, попробуй ещё раз через минуту. 🙂")
