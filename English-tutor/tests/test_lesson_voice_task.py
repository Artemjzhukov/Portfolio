import pytest

from english_tutor import db
from english_tutor.handlers import lessons as lessons_h


class FakeMessage:
    def __init__(self, text=None, tg_id=42, voice=None):
        self.text = text
        self.voice = voice
        self.from_user = type("U", (), {"id": tg_id})()
        self.sent = []
        self.bot = self

    async def answer(self, text, **kw):
        self.sent.append(text)


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


@pytest.fixture
def st():
    return FakeState()


def _lesson():
    return {
        "title": "T",
        "explanation_ru": "e",
        "exercises": [
            {
                "type": "translate",
                "instruction_ru": "i",
                "prompt": "p",
                "answer": "a",
                "hint_ru": "h",
            }
        ],
        "voice_task": "say something",
        "vocab": [{"en": "chunk", "ru": "чанк"}],
    }


@pytest.mark.asyncio
async def test_voice_task_success(conn, st, monkeypatch):
    db.upsert_student(conn, 42, status="active", level="A2")
    import english_tutor.handlers.voice as voice_mod

    async def fake_transcribe(message, bot, llm):
        return "hello world"

    monkeypatch.setattr(voice_mod, "save_and_transcribe", fake_transcribe)
    st.state = lessons_h.LessonSession.voice_task
    await st.update_data(
        lesson=_lesson(),
        meta={"kind": "curriculum", "level": "A2", "topic": "t", "student_id": None},
        voice_task="say something",
    )
    msg = FakeMessage(voice=type("V", (), {"duration": 5})())
    msg.text = None
    await lessons_h.lesson_voice_task(msg, st, conn, llm=None)
    assert any("Расшифровка" in t for t in msg.sent)
    assert any("Задание завершено" in t for t in msg.sent)
    assert st.state is None


@pytest.mark.asyncio
async def test_voice_task_whisper_error(conn, st, monkeypatch):
    db.upsert_student(conn, 42, status="active", level="A2")
    import english_tutor.handlers.voice as voice_mod

    async def boom(message, bot, llm):
        raise RuntimeError("whisper fail")

    monkeypatch.setattr(voice_mod, "save_and_transcribe", boom)
    st.state = lessons_h.LessonSession.voice_task
    await st.update_data(
        lesson=_lesson(),
        meta={"kind": "curriculum", "level": "A2", "topic": "t", "student_id": None},
        voice_task="say",
    )
    msg = FakeMessage(voice=type("V", (), {"duration": 5})())
    msg.text = None
    await lessons_h.lesson_voice_task(msg, st, conn, llm=None)
    assert any("Не удалось распознать" in t for t in msg.sent)
    assert st.state == lessons_h.LessonSession.voice_task


@pytest.mark.asyncio
async def test_voice_task_empty_transcript(conn, st, monkeypatch):
    db.upsert_student(conn, 42, status="active", level="A2")
    import english_tutor.handlers.voice as voice_mod

    async def empty(message, bot, llm):
        return "   "

    monkeypatch.setattr(voice_mod, "save_and_transcribe", empty)
    st.state = lessons_h.LessonSession.voice_task
    await st.update_data(
        lesson=_lesson(),
        meta={"kind": "curriculum", "level": "A2", "topic": "t", "student_id": None},
        voice_task="say",
    )
    msg = FakeMessage(voice=type("V", (), {"duration": 5})())
    msg.text = None
    await lessons_h.lesson_voice_task(msg, st, conn, llm=None)
    assert any("Не расслышал" in t for t in msg.sent)
    assert st.state == lessons_h.LessonSession.voice_task


@pytest.mark.asyncio
async def test_voice_task_text_prompt(conn, st):
    db.upsert_student(conn, 42, status="active", level="A2")
    st.state = lessons_h.LessonSession.voice_task
    await st.update_data(
        lesson=_lesson(),
        meta={"kind": "curriculum", "level": "A2", "topic": "t", "student_id": None},
        voice_task="say",
    )
    msg = FakeMessage(text="hello")
    await lessons_h.lesson_voice_task(msg, st, conn, llm=None)
    assert any("Жду голосовое" in t for t in msg.sent)
    assert st.state == lessons_h.LessonSession.voice_task


@pytest.mark.asyncio
async def test_voice_task_retry_then_success(conn, st, monkeypatch):
    db.upsert_student(conn, 42, status="active", level="A2")
    import english_tutor.handlers.voice as voice_mod

    calls = {"n": 0}

    async def flaky(message, bot, llm):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("fail")
        return "ok"

    monkeypatch.setattr(voice_mod, "save_and_transcribe", flaky)
    st.state = lessons_h.LessonSession.voice_task
    await st.update_data(
        lesson=_lesson(),
        meta={"kind": "curriculum", "level": "A2", "topic": "t", "student_id": None},
        voice_task="say",
    )
    msg1 = FakeMessage(voice=type("V", (), {"duration": 5})())
    msg1.text = None
    await lessons_h.lesson_voice_task(msg1, st, conn, llm=None)
    assert st.state == lessons_h.LessonSession.voice_task
    msg2 = FakeMessage(voice=type("V", (), {"duration": 5})())
    msg2.text = None
    await lessons_h.lesson_voice_task(msg2, st, conn, llm=None)
    assert st.state is None
