"""Regression tests for the /resume router entry point.

`lessons.resume_cmd` decides between restoring a lesson and delegating to the
story handler. A duplicated delegation block used to call
`stories.resume_cmd` twice for the same update, restoring the story session
and then immediately overwriting it again.
"""

import pytest

from english_tutor import db
from english_tutor.handlers import lessons as lessons_h
from english_tutor.handlers import stories as stories_h


class FakeMessage:
    def __init__(self, tg_id=42):
        self.text = "/resume"
        self.from_user = type("U", (), {"id": tg_id})()
        self.sent = []
        self.bot = None

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


@pytest.fixture
def resume_calls(monkeypatch):
    calls = []

    async def fake_resume(message, state, conn):
        calls.append(message)

    monkeypatch.setattr(stories_h, "resume_cmd", fake_resume)
    return calls


def _add_lesson(conn, tg_id=42, content='{"exercises": [], "voice_task": "say"}'):
    cur = conn.execute(
        "INSERT INTO lessons (kind, level, topic, student_id, content_json) "
        "VALUES ('curriculum', 'A2', 't', ?, ?)",
        (tg_id, content),
    )
    conn.commit()
    return cur.lastrowid


def _add_story_session(conn, tg_id=42):
    story_id = db.save_story(conn, tg_id, "A2", "t", '{"comprehension_questions": []}')
    db.save_story_session(conn, tg_id, story_id, "answering_questions")
    return story_id


async def test_resume_calls_story_handler_once(conn, st, resume_calls):
    db.upsert_student(conn, 42, status="active", level="A2")
    _add_story_session(conn)

    msg = FakeMessage()
    await lessons_h.resume_cmd(msg, st, conn)

    assert len(resume_calls) == 1
    assert msg.sent == []


async def test_resume_without_sessions_does_not_touch_story_handler(conn, st, resume_calls):
    db.upsert_student(conn, 42, status="active", level="A2")

    msg = FakeMessage()
    await lessons_h.resume_cmd(msg, st, conn)

    assert resume_calls == []
    assert any("Незавершённых сессий нет" in t for t in msg.sent)


async def test_resume_with_both_sessions_asks_to_choose(conn, st, resume_calls):
    db.upsert_student(conn, 42, status="active", level="A2")
    lesson_id = _add_lesson(conn)
    db.save_lesson_session(conn, 42, lesson_id, "curriculum", "A2", "t")
    _add_story_session(conn)

    msg = FakeMessage()
    await lessons_h.resume_cmd(msg, st, conn)

    assert resume_calls == []
    assert any("Есть и урок, и история" in t for t in msg.sent)


async def test_resume_restores_lesson_without_story_call(conn, st, resume_calls):
    db.upsert_student(conn, 42, status="active", level="A2")
    lesson_id = _add_lesson(conn)
    db.save_lesson_session(
        conn, 42, lesson_id, "curriculum", "A2", "t", stage="voice_task"
    )

    msg = FakeMessage()
    await lessons_h.resume_cmd(msg, st, conn)

    assert resume_calls == []
    assert st.state == lessons_h.LessonSession.voice_task
    assert "Восстановлен урок." in msg.sent
    assert "say" in msg.sent


async def test_resume_rejects_inactive_student(conn, st, resume_calls):
    db.upsert_student(conn, 42, status="pending", level="A2")

    msg = FakeMessage()
    await lessons_h.resume_cmd(msg, st, conn)

    assert resume_calls == []
    assert any("Сначала нужно пройти тест" in t for t in msg.sent)
