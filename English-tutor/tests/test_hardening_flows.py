import pytest

from english_tutor import db
from english_tutor.handlers import lessons as lessons_h
from english_tutor.handlers import registration
from english_tutor.services import invites
from english_tutor.services.lessons import format_drill_prompt


class FakeMessage:
    def __init__(self, text=None, tg_id=42, voice=None):
        self.text = text
        self.voice = voice
        self.from_user = type("U", (), {"id": tg_id})()
        self.sent = []

    async def answer(self, text):
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


class FakeSyncLLM:
    def chat_json(self, system, user):
        return {}


@pytest.fixture
def st():
    return FakeState()


# --- /cancel ---

async def test_cancel_exits_registration_test(conn, st):
    code = invites.create_invite(conn)
    await registration.start(FakeMessage(), st, conn)
    await registration.handle_code(FakeMessage(text=code), st, conn)
    await registration.handle_name(FakeMessage(text="Olya"), st, conn)
    assert st.state == registration.Registration.test_question
    msg = FakeMessage(text="/cancel")
    await registration.cancel(msg, st)
    assert st.state is None and st.data == {}
    assert any("отмен" in t.lower() for t in msg.sent)


async def test_cancel_exits_lesson_and_drill(conn, st):
    db.upsert_student(conn, 42, status="active", level="A2")
    await lessons_h.lessons_cmd(FakeMessage(tg_id=42, text="/lessons"), st, conn)
    assert st.state == lessons_h.LessonSession.active
    msg = FakeMessage(tg_id=42, text="/cancel")
    await lessons_h.cancel(msg, st)
    assert st.state is None and st.data == {}
    await lessons_h.drill_cmd(FakeMessage(tg_id=42, text="/drill"), st, conn)
    assert st.state == lessons_h.Drill.active
    await lessons_h.cancel(FakeMessage(tg_id=42, text="/cancel"), st)
    assert st.state is None


# --- Long lesson → chunked send ---

async def test_long_lesson_sent_in_multiple_chunks(conn, st, monkeypatch):
    long_lesson = {
        "title": "Past Simple",
        "explanation_ru": "объяснение " * 600,  # ~7000 chars
        "exercises": [{"type": "fill_in", "prompt": f"p{i}", "answer": "a",
                       "hint_ru": "h", "accept": []} for i in range(4)],
        "voice_task": "расскажи",
        "vocab": [{"en": f"w{i}", "ru": f"с{i}"} for i in range(8)],
    }
    db.upsert_student(conn, 42, status="active", level="A2")

    async def fake_async_lesson(*a, **k):
        return long_lesson

    monkeypatch.setattr(lessons_h.lessons, "get_or_create_lesson_async", fake_async_lesson)
    msg = FakeMessage(tg_id=42, text="1")
    await lessons_h.lessons_cmd(msg, st, conn)
    await lessons_h.lesson_flow(msg, st, conn, FakeSyncLLM())
    lesson_parts = msg.sent[1:]  # first message is the menu
    assert len(lesson_parts) >= 2
    assert all(len(t) <= 4096 for t in msg.sent)


# --- Russian learner copy ---

def test_drill_prompt_russian():
    assert format_drill_prompt("Мой день") == "🎤 Задание на говорение: Мой день"


# --- Numbering 1–4 ---

def test_question_options_numbered_1_to_4():
    text = registration._question_text(0)
    assert "\n1. " in text and "\n4. " in text and "0. " not in text
    assert "1–4" in text


async def test_answer_1_records_internal_index_0(conn, st):
    code = invites.create_invite(conn)
    await registration.start(FakeMessage(), st, conn)
    await registration.handle_code(FakeMessage(text=code), st, conn)
    await registration.handle_name(FakeMessage(text="Olya"), st, conn)
    await registration.handle_answer(FakeMessage(text="1"), st, conn)
    assert st.data["answers"] == [0]


# --- Config validation ---

def test_invalid_admin_id_names_variable_and_value():
    from english_tutor.config import load_config

    with pytest.raises(ValueError, match="ADMIN_TELEGRAM_ID") as excinfo:
        load_config({"BOT_TOKEN": "t", "GROQ_API_KEY": "g", "ADMIN_TELEGRAM_ID": "abc"})
    assert "abc" in str(excinfo.value)


# --- K2: lesson_progress explicitly deferred ---

def test_lesson_progress_deferred_to_phase2():
    import inspect

    from english_tutor import db as db_mod

    assert "deferred to Phase 2" in inspect.getsource(db_mod)
