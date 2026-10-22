import pytest

from english_tutor import db
from english_tutor.handlers import stories as story_h


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


RAW = {
    "title": "A Busy Day",
    "text_en": "Mia got up late. She **ran out of** time and skipped breakfast.",
    "glossary": [{"en": "run out of", "ru": "исчерпать (время)"}],
    "comprehension_questions": [
        {"q": "Why did Mia skip breakfast?", "options": ["1. She ran out of time", "2. She was full"],
         "answer": "1", "hint_ru": "в тексте: ran out of time"},
        {"q": "Did she have breakfast?", "options": ["1. Yes", "2. No"],
         "answer": "2", "hint_ru": "skipped breakfast"},
    ],
    "retell_prompt": "Перескажи своими словами за 3-4 предложения, используя 'run out of'.",
    "target_chunk": "run out of",
}


class FakeLLM:
    def __init__(self, reply=None):
        self.reply = reply or RAW

    async def chat_json_async(self, system, user):
        return self.reply

    async def transcribe_async(self, path):
        return "Mia woke up and she ran out of time so she skipped breakfast."


@pytest.fixture
def st():
    return FakeState()


async def test_story_requires_active_student(conn, st):
    msg = FakeMessage(text="/story")
    await story_h.story_cmd(msg, st, conn, FakeLLM())
    assert "start" in msg.sent[-1].lower()


async def test_story_cmd_starts_questions(conn, st):
    db.upsert_student(conn, 42, status="active", level="A2")
    msg = FakeMessage(text="/story")
    await story_h.story_cmd(msg, st, conn, FakeLLM())
    assert st.state == story_h.StorySession.answering_questions
    assert any("1/2" in t for t in msg.sent)
    row = conn.execute("SELECT * FROM stories").fetchone()
    assert row is not None


async def test_story_answers_flow_then_retell(conn, st, monkeypatch):
    db.upsert_student(conn, 42, status="active", level="A2")
    await story_h.story_cmd(FakeMessage(text="/story"), st, conn, FakeLLM())

    m1 = FakeMessage(tg_id=42, text="1")
    await story_h.story_answer(m1, st, conn)
    assert any("2/2" in t for t in m1.sent)

    m2 = FakeMessage(tg_id=42, text="2")
    await story_h.story_answer(m2, st, conn)
    assert st.state == story_h.StorySession.waiting_retell
    assert any("Retell" in t or "говорение" in t for t in m2.sent)

    import english_tutor.handlers.voice as voice_mod

    async def fake_transcribe(message, bot, llm):
        return "Mia woke up and she ran out of time so she skipped breakfast."

    monkeypatch.setattr(voice_mod, "save_and_transcribe", fake_transcribe)
    m3 = FakeMessage(tg_id=42, voice=type("V", (), {"duration": 5})())
    m3.text = None
    await story_h.story_retell(m3, st, conn, FakeLLM())
    assert st.state is None
    assert any("Расшифровка" in t for t in m3.sent)
    prog = conn.execute("SELECT * FROM story_progress").fetchone()
    assert prog["questions_score"] == 2
    card = conn.execute("SELECT * FROM srs_cards WHERE student_id=42").fetchone()
    assert card is not None


async def test_story_wrong_answer_continues(conn, st):
    db.upsert_student(conn, 42, status="active", level="A2")
    await story_h.story_cmd(FakeMessage(text="/story"), st, conn, FakeLLM())
    m1 = FakeMessage(tg_id=42, text="2")
    await story_h.story_answer(m1, st, conn)
    assert any("Не совсем" in t for t in m1.sent)
    assert st.state == story_h.StorySession.answering_questions


async def test_story_retell_rejects_text(conn, st):
    db.upsert_student(conn, 42, status="active", level="A2")
    await story_h.story_cmd(FakeMessage(text="/story"), st, conn, FakeLLM())
    await story_h.story_answer(FakeMessage(tg_id=42, text="1"), st, conn)
    await story_h.story_answer(FakeMessage(tg_id=42, text="2"), st, conn)
    m = FakeMessage(tg_id=42, text="я перескатываю ответ текстом")
    await story_h.story_retell(m, st, conn, FakeLLM())
    assert any("голосовое" in t.lower() for t in m.sent)
    assert st.state == story_h.StorySession.waiting_retell


class FailingFakeLLM:
    """LLM that raises on story generation (transcription still works)."""

    async def chat_json_async(self, system, user):
        raise RuntimeError("LLM exploded")

    async def transcribe_async(self, path):
        return "transcript"


async def test_story_retell_transcription_failure_no_progress(conn, st, monkeypatch):
    """Empty transcript (silence/noise) → retry prompt, no progress or SRS cards."""
    db.upsert_student(conn, 42, status="active", level="A2")
    await story_h.story_cmd(FakeMessage(text="/story"), st, conn, FakeLLM())
    await story_h.story_answer(FakeMessage(tg_id=42, text="1"), st, conn)
    await story_h.story_answer(FakeMessage(tg_id=42, text="2"), st, conn)

    import english_tutor.handlers.voice as voice_mod

    async def silent_transcribe(message, bot, llm):
        return ""  # Whisper returns nothing for silence

    monkeypatch.setattr(voice_mod, "save_and_transcribe", silent_transcribe)
    m = FakeMessage(tg_id=42, voice=type("V", (), {"duration": 5})())
    m.text = None
    await story_h.story_retell(m, st, conn, FakeLLM())
    assert any("расслышал" in t.lower() for t in m.sent)
    assert st.state == story_h.StorySession.waiting_retell
    assert conn.execute("SELECT * FROM story_progress").fetchone() is None
    assert conn.execute(
        "SELECT * FROM srs_cards WHERE student_id=42"
    ).fetchone() is None


async def test_story_retell_transcription_error_no_progress(conn, st, monkeypatch):
    """VoiceTranscribeError (service failure) → helpful retry, no DB writes, FSM kept."""
    from english_tutor.handlers.voice import VoiceTranscribeError

    db.upsert_student(conn, 42, status="active", level="A2")
    await story_h.story_cmd(FakeMessage(text="/story"), st, conn, FakeLLM())
    await story_h.story_answer(FakeMessage(tg_id=42, text="1"), st, conn)
    await story_h.story_answer(FakeMessage(tg_id=42, text="2"), st, conn)

    import english_tutor.handlers.voice as voice_mod

    async def failing_transcribe(message, bot, llm):
        raise VoiceTranscribeError("download/transcription failed")

    monkeypatch.setattr(voice_mod, "save_and_transcribe", failing_transcribe)
    m = FakeMessage(tg_id=42, voice=type("V", (), {"duration": 5})())
    m.text = None
    await story_h.story_retell(m, st, conn, FakeLLM())
    # Helpful retry message (distinct from the "silence" message)
    assert any("распозн" in t.lower() and "попробуй" in t.lower() for t in m.sent)
    # FSM stays in waiting_retell so the learner can retry
    assert st.state == story_h.StorySession.waiting_retell
    # No story progress or SRS cards recorded
    assert conn.execute("SELECT * FROM story_progress").fetchone() is None
    assert conn.execute(
        "SELECT * FROM srs_cards WHERE student_id=42"
    ).fetchone() is None


async def test_story_cmd_generation_failure_no_story(conn, st):
    """LLM generation raises → user-friendly error, no story saved, FSM clean."""
    db.upsert_student(conn, 42, status="active", level="A2")
    msg = FakeMessage(text="/story")
    await story_h.story_cmd(msg, st, conn, FailingFakeLLM())
    assert any("историй" in t.lower() or "сервис" in t.lower() for t in msg.sent)
    assert st.state is None  # never entered answering_questions
    assert conn.execute("SELECT * FROM stories").fetchone() is None
