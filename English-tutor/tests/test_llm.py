import pytest

from english_tutor.llm.groq_service import LLMParseError, GroqService
from english_tutor.llm.prompts import (
    LESSON_SYSTEM_PROMPT,
    VOICE_LEVEL_PROMPT,
    build_lesson_user_prompt,
)


class FakeRaw:
    def __init__(self, content):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]


class FakeGroq:
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.script = []
        self.audio = type("A", (), {"transcriptions": self})()
        self.chat = type("K", (), {"completions": self})()

    def create(self, model=None, **kw):
        return self.script.pop(0)


def test_transcribe_returns_text():
    c = FakeGroq(api_key="k")
    s = GroqService(api_key="k", client=c)
    c.script = [type("T", (), {"text": "hello world"})()]
    assert s.transcribe("x.ogg") == "hello world"


def test_chat_json_parses_clean_json():
    c = FakeGroq(api_key="k")
    s = GroqService(api_key="k", client=c)
    c.script = [FakeRaw('{"reply": "ok"}')]
    assert s.chat_json("sys", "usr") == {"reply": "ok"}


def test_chat_json_extracts_embedded_json():
    c = FakeGroq(api_key="k")
    s = GroqService(api_key="k", client=c)
    c.script = [FakeRaw('Sure!\n```json\n{"a": 1}\n```')]
    assert s.chat_json("sys", "usr") == {"a": 1}


def test_chat_json_retries_then_raises():
    c = FakeGroq(api_key="k")
    s = GroqService(api_key="k", client=c)
    c.script = [FakeRaw("garbage"), FakeRaw("still garbage")]
    with pytest.raises(LLMParseError):
        s.chat_json("sys", "usr")


def test_prompts_exist_and_are_substantive():
    assert "A2" in build_lesson_user_prompt("A2", "Present Simple")
    assert "json" in LESSON_SYSTEM_PROMPT.lower()
    assert "level" in VOICE_LEVEL_PROMPT
