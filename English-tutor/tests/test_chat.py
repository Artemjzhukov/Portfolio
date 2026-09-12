import pytest

from english_tutor import db
from english_tutor.handlers import chat as chat_h
from english_tutor.services import chat as chat_svc


class FakeMessage:
    def __init__(self, text=None, tg_id=42, voice=None):
        self.text = text
        self.voice = voice
        self.from_user = type("U", (), {"id": tg_id})()
        self.sent = []
        self.bot = self

    async def answer(self, text):
        self.sent.append(text)

    async def download(self, *a, **k):
        raise AssertionError("not expected")


class FakeState:
    def __init__(self):
        self.state, self.data = None, {}

    async def set_state(self, s):
        self.state = s

    async def update_data(self, **kw):
        self.data.update(kw)

    async def get_data(self):
        return dict(self.data)

    async def clear(self):
        self.state, self.data = None, {}


REPLY = {
    "reply": "Sounds great! I love cooking too.",
    "corrections": [
        {"wrong": "I make a cake yesterday", "right": "I made a cake yesterday",
         "hint_ru": "прошедшее время — Past Simple"},
    ],
}


class FakeLLM:
    def __init__(self, reply=None):
        self.reply = reply or REPLY

    async def chat_json_async(self, system, user):
        return self.reply


# --- service-level ---

def test_parse_chat_ok():
    assert chat_svc.parse_chat(REPLY)["reply"].startswith("Sounds")


def test_parse_chat_rejects_bad():
    with pytest.raises(chat_svc.ChatFormatError):
        chat_svc.parse_chat({"corrections": []})
    with pytest.raises(chat_svc.ChatFormatError):
        chat_svc.parse_chat({"reply": "x", "corrections": [{"wrong": 1}]})


def test_format_chat_answer_with_corrections():
    text = chat_svc.format_chat_answer(REPLY)
    assert "Sounds great!" in text
    assert "📝 Исправления:" in text
    assert "Past Simple" in text


def test_format_chat_answer_no_corrections():
    text = chat_svc.format_chat_answer({"reply": "Nice!", "corrections": []})
    assert "ошибок нет" in text


def test_system_prompt_contains_level():
    prompt = chat_svc.chat_system_prompt("B1")
    assert "B1" in prompt and "JSON" in prompt


# --- handler flow ---

@pytest.fixture
def st():
    return FakeState()


async def test_chat_requires_active_student(conn, st):
    msg = FakeMessage(text="/chat")
    await chat_h.chat_cmd(msg, st, conn)
    assert "start" in msg.sent[-1].lower()


async def test_chat_flow_with_correction(conn, st):
    db.upsert_student(conn, 42, status="active", level="B1")
    msg = FakeMessage(text="/chat")
    await chat_h.chat_cmd(msg, st, conn)
    assert st.state == chat_h.Chat.active
    assert any("Темы на выбор" in t for t in msg.sent)

    msg = FakeMessage(tg_id=42, text="I make a cake yesterday")
    await chat_h.chat_flow(msg, st, conn, FakeLLM())
    assert st.state == chat_h.Chat.active  # chat continues
    assert any("📝 Исправления:" in t for t in msg.sent)
    # correction stored + auto-added to SRS
    row = conn.execute("SELECT * FROM corrections WHERE student_id=42").fetchone()
    assert row["source"] == "chat" and row["right"] == "I made a cake yesterday"
    card = conn.execute("SELECT * FROM srs_cards WHERE student_id=42").fetchone()
    assert card["word_en"] == "I made a cake yesterday"


async def test_chat_text_len_limit(conn, st):
    db.upsert_student(conn, 42, status="active", level="B1")
    await chat_h.chat_cmd(FakeMessage(text="/chat"), st, conn)
    msg = FakeMessage(tg_id=42, text="x" * 2000)
    await chat_h.chat_flow(msg, st, conn, FakeLLM())
    assert "длинное" in msg.sent[-1]


async def test_chat_slash_command_exits(conn, st):
    db.upsert_student(conn, 42, status="active", level="B1")
    await chat_h.chat_cmd(FakeMessage(text="/chat"), st, conn)
    msg = FakeMessage(tg_id=42, text="/lessons")
    await chat_h.chat_flow(msg, st, conn, FakeLLM())
    assert st.state is None
    assert any("Вышел из чата" in t for t in msg.sent)


async def test_chat_media_reprompts(conn, st):
    db.upsert_student(conn, 42, status="active", level="B1")
    await chat_h.chat_cmd(FakeMessage(text="/chat"), st, conn)
    msg = FakeMessage(tg_id=42)
    msg.text = None
    await chat_h.chat_flow(msg, st, conn, FakeLLM())
    assert any("голосовое" in t.lower() for t in msg.sent)
