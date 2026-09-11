import asyncio
import time

import pytest

from english_tutor.llm.groq_service import LLMParseError, GroqService, _extract_json
from english_tutor.utils.telegram import split_for_telegram


# --- Telegram 4096-char limit ---

def test_split_short_text_single_chunk():
    assert split_for_telegram("привет") == ["привет"]


def test_split_long_text_chunks_within_limit_no_loss():
    text = "\n".join(f"строка {i}" for i in range(1000))
    chunks = split_for_telegram(text)
    assert len(chunks) >= 2
    assert all(0 < len(c) <= 4096 for c in chunks)
    assert "\n".join(chunks).count("строка") == 1000


def test_split_no_newlines_hard_split():
    chunks = split_for_telegram("a" * 10_000)
    assert sum(map(len, chunks)) == 10_000
    assert all(len(c) <= 4096 for c in chunks)


def test_split_custom_limit():
    chunks = split_for_telegram("b" * 250, limit=100)
    assert len(chunks) == 3 and all(len(c) <= 100 for c in chunks)


# --- Non-blocking Groq ---

class _ClientShell:
    """Mimics the groq client surface: .chat.completions.create(...)"""
    def __init__(self, create_fn):
        self._create_fn = create_fn
        self.chat = type("K", (), {"completions": self})()

    def create(self, model=None, messages=None, temperature=None, **kw):
        return self._create_fn(messages)


def _reply(content):
    return type("R", (), {"choices": [type(
        "C", (), {"message": type("M", (), {"content": content})()})()]})()


async def test_chat_json_async_nonblocking_wallclock():
    def slow_create(messages):
        time.sleep(0.3)
        return _reply('{"ok": 1}')

    svc = GroqService(api_key="k", client=_ClientShell(slow_create))
    start = time.monotonic()
    results = await asyncio.gather(*(svc.chat_json_async("s", "u") for _ in range(4)))
    elapsed = time.monotonic() - start
    assert all(r == {"ok": 1} for r in results)
    assert elapsed < 0.9  # sequential blocking would be ~1.2s


def test_extract_json_braces_inside_strings():
    tricky = 'Sure! {"a": "value with } and { inside", "b": 2} hope this helps'
    assert _extract_json(tricky) == {"a": "value with } and { inside", "b": 2}


async def test_chat_json_retry_appends_stricter_instruction():
    calls = []

    def flaky_create(messages):
        calls.append(messages[0]["content"])
        if len(calls) == 1:
            return _reply("garbage, no json here")
        return _reply('{"ok": 1}')

    svc = GroqService(api_key="k", client=_ClientShell(flaky_create))
    assert await svc.chat_json_async("sys", "usr") == {"ok": 1}
    assert calls[0] == "sys"
    assert "ONLY one valid JSON" in calls[1]


# --- Central error handler ---

async def test_error_handler_generic_copy():
    from english_tutor.handlers import errors as errors_h

    event = type("E", (), {"message": FakeMsg()})()
    await errors_h.on_error(event, RuntimeError("boom"))
    assert "не так" in event.message.sent[0]


async def test_error_handler_llm_copy():
    from english_tutor.handlers import errors as errors_h

    event = type("E", (), {"message": FakeMsg()})()
    await errors_h.on_error(event, LLMParseError("bad json"))
    assert "сервис" in event.message.sent[0]


def test_redact_secrets(monkeypatch):
    from english_tutor.handlers import errors as errors_h

    monkeypatch.setenv("GROQ_API_KEY", "sk-secret123")
    assert errors_h.redact("key=sk-secret123 end") == "key=<REDACTED> end"


def test_errors_router_registered_in_dispatcher():
    from english_tutor.handlers import errors as errors_h

    # aiogram forbids re-attaching a module router to a second dispatcher,
    # so we assert the essential property: the errors observer has a handler
    # and bot.py imports the router (see bot.py include).
    assert errors_h.router.errors.handlers
    import inspect

    from english_tutor import bot as bot_mod

    assert "errors.router" in inspect.getsource(bot_mod)


class FakeMsg:
    def __init__(self):
        self.sent = []

    async def answer(self, text):
        self.sent.append(text)
