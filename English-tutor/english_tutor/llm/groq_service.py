import json


class LLMParseError(Exception):
    pass


class GroqService:
    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile",
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
            reply = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                temperature=0.4,
            )
            content = reply.choices[0].message.content
            try:
                return json.loads(_extract_json(content))
            except (ValueError, json.JSONDecodeError):
                continue
        raise LLMParseError(f"Could not parse JSON from LLM reply: {content[:200]!r}")


def _extract_json(text: str) -> str:
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise ValueError("no balanced JSON object found")
