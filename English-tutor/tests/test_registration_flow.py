import pytest

from english_tutor import db
from english_tutor.handlers import registration
from english_tutor.services import invites, placement


class FakeMessage:
    def __init__(self, text=None, tg_id=42, voice=None):
        self.text = text
        self.voice = voice
        self.from_user = type("U", (), {"id": tg_id})()
        self.sent = []

    async def answer(self, text):
        self.sent.append(text)


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


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


@pytest.fixture
def bot():
    return FakeBot()


@pytest.fixture
def llm():
    class L:
        def chat_json(self, system, user):
            return {"level": "A2"}

    return L()


async def _register_and_answer(conn, st):
    code = invites.create_invite(conn)
    await registration.start(FakeMessage(), st, conn)
    await registration.handle_code(FakeMessage(text=code), st, conn)
    await registration.handle_name(FakeMessage(text="Olya"), st, conn)
    for _ in range(20):
        await registration.handle_answer(FakeMessage(text="0"), st, conn)


async def test_start_without_code_asks_for_code(conn, st):
    msg = FakeMessage()
    await registration.start(msg, st, conn)
    assert st.state == registration.Registration.waiting_code
    assert "код" in msg.sent[0].lower()


async def test_active_student_gets_welcome(conn, st):
    db.upsert_student(conn, 42, status="active", level="B1")
    msg = FakeMessage()
    await registration.start(msg, st, conn)
    assert st.state is None
    assert "lessons" in msg.sent[0]


async def test_bad_code_keeps_asking(conn, st):
    await registration.start(FakeMessage(), st, conn)
    await registration.handle_code(FakeMessage(text="TUTOR-NOPE"), st, conn)
    assert st.state == registration.Registration.waiting_code


async def test_code_then_name_starts_test(conn, st):
    await _register_and_answer_early(conn, st)
    s = db.get_student(conn, 42)
    assert s["name"] == "Olya" and s["status"] == "testing"
    assert st.state == registration.Registration.test_question
    assert st.data["qidx"] >= 1 and len(st.data["answers"]) >= 1


async def _register_and_answer_early(conn, st):
    code = invites.create_invite(conn)
    await registration.start(FakeMessage(), st, conn)
    await registration.handle_code(FakeMessage(text=code), st, conn)
    await registration.handle_name(FakeMessage(text="Olya"), st, conn)
    await registration.handle_answer(FakeMessage(text="1"), st, conn)


async def test_full_flow_reaches_voice_step(conn, st):
    await _register_and_answer(conn, st)
    assert st.state == registration.Registration.waiting_voice
    assert "голос" in st.data["last_question"].lower()


async def test_voice_completes_test_and_notifies_admin(conn, st, llm, bot, monkeypatch):
    import english_tutor.handlers.voice as voice_mod

    async def fake_transcribe(message, bot_, llm_):
        return "my day was good"

    monkeypatch.setattr(voice_mod, "save_and_transcribe", fake_transcribe)
    await _register_and_answer(conn, st)
    msg = FakeMessage(tg_id=42)
    await registration.handle_voice_test(msg, st, conn, llm, admin_id=99, bot=bot)
    assert db.get_student(conn, 42)["status"] == "pending"
    row = conn.execute("SELECT * FROM test_results").fetchone()
    assert row["written_score"] == placement.score_written([0] * 20)
    assert row["suggested_level"] == "A2"
    assert bot.sent and bot.sent[0][0] == 99
    assert st.state is None


async def test_non_numeric_answer_reprompts(conn, st):
    await _register_and_answer_early(conn, st)
    before = st.data["qidx"]
    msg = FakeMessage(text="hello")
    await registration.handle_answer(msg, st, conn)
    assert st.data["qidx"] == before
    assert "0–3" in msg.sent[-1]


class FakeLLMLections:
    def __init__(self, reply):
        self.reply = reply

    def chat_json(self, system, user):
        return self.reply


async def test_voice_during_mc_questions_reprompts_clearly(conn, st):
    await _register_and_answer_early(conn, st)
    before = st.data["qidx"]
    msg = FakeMessage(tg_id=42, voice=type("V", (), {"duration": 10})())
    msg.text = None
    await registration.handle_answer(msg, st, conn)
    assert st.data["qidx"] == before
    assert "0–3" in msg.sent[-1] and "голос" in msg.sent[-1].lower()


async def test_text_at_voice_step_prompts_for_voice(conn, st, llm, bot, monkeypatch):
    await _register_and_answer(conn, st)
    msg = FakeMessage(tg_id=42, text="hello")
    await registration.handle_voice_test(msg, st, conn, llm, admin_id=99, bot=bot)
    assert st.state == registration.Registration.waiting_voice  # still waiting
    assert "голосов" in msg.sent[-1].lower()


async def test_lesson_flow_accepts_voice_answer(conn, st, monkeypatch):
    import english_tutor.handlers.voice as voice_mod
    from english_tutor.handlers import lessons as lessons_h
    from tests.test_lessons import RAW

    db.upsert_student(conn, 42, status="active", level="A2")
    msg = FakeMessage(tg_id=42, text="1")
    await lessons_h.lessons_cmd(msg, st, conn)
    await lessons_h.lesson_flow(msg, st, conn, FakeLLMLections(RAW))
    assert any("📖" in t for t in msg.sent)

    msg2 = FakeMessage(tg_id=42, voice=type("V", (), {"duration": 10})())
    msg2.text = None
    msg2.bot = FakeBot()

    async def fake_transcribe(message, bot, llm):
        return "Went"

    monkeypatch.setattr(voice_mod, "save_and_transcribe", fake_transcribe)
    await lessons_h.lesson_flow(msg2, st, conn, FakeLLMLections(RAW))
    assert any("✅" in t for t in msg2.sent)


async def test_lesson_flow_ignores_sticker(conn, st):
    from english_tutor.handlers import lessons as lessons_h
    from tests.test_lessons import RAW

    db.upsert_student(conn, 42, status="active", level="A2")
    msg = FakeMessage(tg_id=42, text="1")
    await lessons_h.lessons_cmd(msg, st, conn)
    await lessons_h.lesson_flow(msg, st, conn, FakeLLMLections(RAW))

    msg2 = FakeMessage(tg_id=42)  # no text, no voice -> sticker/photo
    msg2.text = None
    await lessons_h.lesson_flow(msg2, st, conn, FakeLLMLections(RAW))
    assert any("текстом или голосом" in t for t in msg2.sent)
