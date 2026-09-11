import asyncio
import os
import tempfile


class VoiceTranscribeError(Exception):
    pass


async def save_and_transcribe(message, bot, llm) -> str:
    if getattr(message, "voice", None) is None:
        raise VoiceTranscribeError("no voice in message")
    fd, path = tempfile.mkstemp(suffix=".ogg")
    os.close(fd)
    try:
        await bot.download(message.voice, destination=path)
        if hasattr(llm, "transcribe_async"):
            return await llm.transcribe_async(path)
        return await asyncio.to_thread(llm.transcribe, path)
    finally:
        if os.path.exists(path):
            os.remove(path)
