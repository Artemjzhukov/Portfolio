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


# ─── Phase 4.1b: Session recovery after restart ──────────────────────────


async def test_resume_answering_questions_after_restart(conn, st):
    """Simulate restart: discard FSM state, /resume restores to answering_questions."""
    db.upsert_student(conn, 42, status="active", level="A2")
    # Start a story in one "session" (in-memory FSM state)
    await story_h.story_cmd(FakeMessage(text="/story"), st, conn, FakeLLM())
    await story_h.story_answer(FakeMessage(tg_id=42, text="1"), st, conn)
    # q_idx=1, correct=1, stage=answering_questions persisted

    # Simulate restart: discard in-memory FSM state but keep SQLite
    st2 = FakeState()  # fresh state = lost MemoryStorage

    # No active session should exist in in-memory state
    assert st2.state is None

    # Resume from durable storage
    msg = FakeMessage(text="/resume", tg_id=42)
    await story_h.resume_cmd(msg, st2, conn)

    assert st2.state == story_h.StorySession.answering_questions
    assert st2.data["q_idx"] == 1
    assert st2.data["correct"] == 1
    assert any("Вопрос 2/2" in t for t in msg.sent)

    # Verify the active session is still in the DB (not consumed)
    sess = db.get_active_session(conn, 42)
    assert sess is not None
    assert sess["stage"] == "answering_questions"
    assert sess["q_idx"] == 1


async def test_resume_waiting_retell_after_restart(conn, st):
    """Simulate restart: discard FSM state, /resume restores to waiting_retell."""
    db.upsert_student(conn, 42, status="active", level="A2")
    await story_h.story_cmd(FakeMessage(text="/story"), st, conn, FakeLLM())
    await story_h.story_answer(FakeMessage(tg_id=42, text="1"), st, conn)
    await story_h.story_answer(FakeMessage(tg_id=42, text="2"), st, conn)

    # Simulate restart
    st2 = FakeState()
    msg = FakeMessage(text="/resume", tg_id=42)
    await story_h.resume_cmd(msg, st2, conn)

    assert st2.state == story_h.StorySession.waiting_retell
    assert st2.data["correct"] == 2
    assert any("голос" in t.lower() or "Retell" in t for t in msg.sent)

    sess = db.get_active_session(conn, 42)
    assert sess["stage"] == "waiting_retell"
    assert sess["correct"] == 2


async def test_resume_preserves_q_idx_and_score(conn, st):
    """Verify q_idx and correct are faithfully restored."""
    db.upsert_student(conn, 42, status="active", level="A2")
    await story_h.story_cmd(FakeMessage(text="/story"), st, conn, FakeLLM())

    # Answer first question (correct=1, q_idx advances to 1)
    await story_h.story_answer(FakeMessage(tg_id=42, text="1"), st, conn)
    # Directly set an arbitrary score for testing
    db.save_story_session(conn, 42, st.data["story_id"], "answering_questions", 1, 5)

    st2 = FakeState()
    await story_h.resume_cmd(FakeMessage(text="/resume", tg_id=42), st2, conn)
    assert st2.state == story_h.StorySession.answering_questions
    assert st2.data["q_idx"] == 1
    assert st2.data["correct"] == 5


async def test_resume_isolates_students(conn, st):
    """Student A's /resume must never see student B's story."""
    db.upsert_student(conn, 42, status="active", level="A2")
    db.upsert_student(conn, 99, status="active", level="A2")

    # Student A starts a story
    await story_h.story_cmd(FakeMessage(text="/story", tg_id=42), st, conn, FakeLLM())
    sess_a = db.get_active_session(conn, 42)
    assert sess_a is not None

    # Student B tries /resume — should see "no unfinished story"
    st_b = FakeState()
    msg_b = FakeMessage(text="/resume", tg_id=99)
    await story_h.resume_cmd(msg_b, st_b, conn)

    assert st_b.state is None
    assert any("нет" in t.lower() for t in msg_b.sent)

    # Student A's session is still intact
    sess_a_after = db.get_active_session(conn, 42)
    assert sess_a_after is not None
    assert sess_a_after["story_id"] == sess_a["story_id"]


async def test_complete_story_removes_active_session(conn, st):
    """On completion, the active-session row is removed in the same transaction."""
    db.upsert_student(conn, 42, status="active", level="A2")
    await story_h.story_cmd(FakeMessage(text="/story"), st, conn, FakeLLM())
    await story_h.story_answer(FakeMessage(tg_id=42, text="1"), st, conn)
    await story_h.story_answer(FakeMessage(tg_id=42, text="2"), st, conn)

    assert db.get_active_session(conn, 42) is not None

    # Mock voice transcription
    import english_tutor.handlers.voice as voice_mod
    async def good_transcribe(message, bot, llm):
        return "Mia woke up and she ran out of time so she skipped breakfast."
    voice_mod.save_and_transcribe = good_transcribe

    m = FakeMessage(tg_id=42, voice=type("V", (), {"duration": 5})())
    m.text = None
    await story_h.story_retell(m, st, conn, FakeLLM())

    # Active session removed
    assert db.get_active_session(conn, 42) is None
    # But story_progress exists
    assert conn.execute(
        "SELECT * FROM story_progress WHERE student_id=42"
    ).fetchone() is not None


async def test_transcription_failure_preserves_session(conn, st, monkeypatch):
    """VoiceTranscribeError during retell keeps the active session for retry."""
    from english_tutor.handlers.voice import VoiceTranscribeError

    db.upsert_student(conn, 42, status="active", level="A2")
    await story_h.story_cmd(FakeMessage(text="/story"), st, conn, FakeLLM())
    await story_h.story_answer(FakeMessage(tg_id=42, text="1"), st, conn)
    await story_h.story_answer(FakeMessage(tg_id=42, text="2"), st, conn)

    assert db.get_active_session(conn, 42) is not None

    import english_tutor.handlers.voice as voice_mod
    async def failing_transcribe(message, bot, llm):
        raise VoiceTranscribeError("service unavailable")

    monkeypatch.setattr(voice_mod, "save_and_transcribe", failing_transcribe)

    m = FakeMessage(tg_id=42, voice=type("V", (), {"duration": 5})())
    m.text = None
    await story_h.story_retell(m, st, conn, FakeLLM())

    # Retry message sent
    assert any("распозн" in t.lower() or "попробуй" in t.lower() for t in m.sent)
    # FSM still in waiting_retell
    assert st.state == story_h.StorySession.waiting_retell
    # Active session still in DB
    sess = db.get_active_session(conn, 42)
    assert sess is not None
    assert sess["stage"] == "waiting_retell"
    # No story progress recorded
    assert conn.execute("SELECT * FROM story_progress WHERE student_id=42").fetchone() is None


async def test_cancel_removes_active_session(conn, st):
    """/cancel clears both in-memory FSM and the durable active session."""
    db.upsert_student(conn, 42, status="active", level="A2")
    await story_h.story_cmd(FakeMessage(text="/story"), st, conn, FakeLLM())
    await story_h.story_answer(FakeMessage(tg_id=42, text="1"), st, conn)

    assert db.get_active_session(conn, 42) is not None
    assert st.state == story_h.StorySession.answering_questions

    msg = FakeMessage(text="/cancel", tg_id=42)
    await story_h.story_cancel(msg, st, conn)

    assert st.state is None
    assert db.get_active_session(conn, 42) is None
    # Story in stories table should still exist (not deleted)
    assert conn.execute("SELECT * FROM stories WHERE student_id=42").fetchone() is not None


async def test_resume_no_session(conn, st):
    """/resume with no active session → helpful message, FSM untouched."""
    db.upsert_student(conn, 42, status="active", level="A2")
    msg = FakeMessage(text="/resume", tg_id=42)
    await story_h.resume_cmd(msg, st, conn)
    assert any("нет" in t.lower() or "начни" in t.lower() for t in msg.sent)
    assert st.state is None


async def test_resume_missing_story_safe(conn, st):
    """Orphaned session (story deleted from stories table) → cleaned up safely."""
    db.upsert_student(conn, 42, status="active", level="A2")
    # Create a real story, then delete it leaving the session orphaned
    await story_h.story_cmd(FakeMessage(text="/story"), st, conn, FakeLLM())
    story_id = st.data["story_id"]
    # Delete the story row directly, leaving the active_session orphaned
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DELETE FROM stories WHERE id=?", (story_id,))
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")

    msg = FakeMessage(text="/resume", tg_id=42)
    await story_h.resume_cmd(msg, st, conn)

    # Should clean up the orphaned session and suggest /story
    assert any("поврежд" in t.lower() or "заново" in t.lower() for t in msg.sent)
    assert db.get_active_session(conn, 42) is None
    assert st.state is None


async def test_resume_student_id_mismatch_safe(conn, st):
    """Session pointing to another student's story → cleaned up safely."""
    db.upsert_student(conn, 42, status="active", level="A2")
    db.upsert_student(conn, 99, status="active", level="A2")

    # Student 99 saves a story
    await story_h.story_cmd(FakeMessage(text="/story", tg_id=99), FakeState(), conn, FakeLLM())
    story_row = conn.execute("SELECT * FROM stories WHERE student_id=99").fetchone()
    story_id = story_row["id"]

    # Student 42 has a session pointing to student 99's story (simulated corruption)
    db.save_story_session(conn, 42, story_id, "answering_questions", 0, 0)

    msg = FakeMessage(text="/resume", tg_id=42)
    await story_h.resume_cmd(msg, st, conn)

    # Should detect ownership mismatch and clean up
    assert any("поврежд" in t.lower() or "заново" in t.lower() for t in msg.sent)
    assert db.get_active_session(conn, 42) is None
    # Student 99's story is untouched
    assert conn.execute(
        "SELECT * FROM stories WHERE student_id=99 AND id=?", (story_id,)
    ).fetchone() is not None
