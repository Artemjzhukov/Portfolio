import asyncio
import json


class LLMParseError(Exception):
    pass


class GroqService:
    def __init__(self, api_key: str, model: str = "openai/gpt-oss-120b",
                 whisper_model: str = "whisper-large-v3", client=None):
        self.model = model
        self.whisper_model = whisper_model
        if client is None:
            from groq import Groq

            client = Groq(api_key=api_key)
        self._client = client

    def transcribe(self, audio_path: str) -> str:
        with open(audio_path, "rb") as f:
            result = self._client.audio.transcriptions.create(
                model=self.whisper_model, file=f, response_format="text"
            )
        return result.text.strip() if hasattr(result, "text") else str(result).strip()

    def chat_json(self, system: str, user: str) -> dict:
        content = None
        for _attempt in range(2):
            system_prompt = system
            if _attempt == 1:
                system_prompt = (system + "\nIMPORTANT: Reply with ONLY one valid JSON "
                                           "object. No markdown, no commentary.")
            reply = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system_prompt},
                          {"role": "user", "content": user}],
                temperature=0.4,
            )
            content = reply.choices[0].message.content
            try:
                return _extract_json(content)
            except ValueError:
                continue
        raise LLMParseError(f"Could not parse JSON from LLM reply: {content[:200]!r}")

    async def transcribe_async(self, audio_path: str) -> str:
        return await asyncio.to_thread(self.transcribe, audio_path)

    async def chat_json_async(self, system: str, user: str) -> dict:
        return await asyncio.to_thread(self.chat_json, system, user)


def _extract_json(text: str):
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found")
    # raw_decode respects string boundaries, unlike brace counting
    obj, _end = json.JSONDecoder().raw_decode(text[start:])
    return obj

