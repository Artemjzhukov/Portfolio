import pytest

from english_tutor import db
from english_tutor.handlers import registration as reg_h
from english_tutor.utils.keyboards import admin_main_keyboard, learner_main_keyboard


class FakeMessage:
    def __init__(self, text=None, tg_id=1, voice=None):
        self.text = text
        self.voice = voice
        self.from_user = type("U", (), {"id": tg_id})()
        self.sent = []
        self.reply_markup = None
        self.bot = self

    async def answer(self, text, reply_markup=None):
        self.sent.append(text)
        self.reply_markup = reply_markup


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


@pytest.mark.asyncio
async def test_admin_start_sends_admin_keyboard(conn):
    admin_id = 1
    db.upsert_student(conn, admin_id, status="active", level="B1")
    msg = FakeMessage(tg_id=admin_id)
    st = FakeState()
    await reg_h.start(msg, st, conn, admin_id=admin_id)
    assert msg.reply_markup is not None
    assert msg.reply_markup == admin_main_keyboard()


@pytest.mark.asyncio
async def test_non_admin_start_no_admin_keyboard(conn):
    db.upsert_student(conn, 2, status="active", level="B1")
    msg = FakeMessage(tg_id=2)
    st = FakeState()
    await reg_h.start(msg, st, conn, admin_id=1)
    assert msg.reply_markup is None or msg.reply_markup != admin_main_keyboard()


@pytest.mark.asyncio
async def test_admin_button_students_routes(conn):
    from english_tutor.handlers import menu as menu_h

    admin_id = 1
    db.upsert_student(conn, admin_id, status="active", level="B1")
    msg = FakeMessage(text="👥 Студенты", tg_id=admin_id)
    st = FakeState()
    # monkeypatch admin.students
    called = {}

    async def fake_students(message, conn, admin_id):
        called["students"] = True

    import english_tutor.handlers.admin as admin_h

    orig = admin_h.students
    admin_h.students = fake_students
    try:
        await menu_h.btn_students(msg, st, conn, admin_id)
    finally:
        admin_h.students = orig
    assert called.get("students") is True


@pytest.mark.asyncio
async def test_admin_button_invite_routes(conn):
    from english_tutor.handlers import menu as menu_h

    admin_id = 1
    db.upsert_student(conn, admin_id, status="active", level="B1")
    msg = FakeMessage(text="➕ Инвайт", tg_id=admin_id)
    st = FakeState()
    called = {}

    async def fake_invite(message, conn, admin_id):
        called["invite"] = True

    import english_tutor.handlers.admin as admin_h

    orig = admin_h.invite
    admin_h.invite = fake_invite
    try:
        await menu_h.btn_invite(msg, st, conn, admin_id)
    finally:
        admin_h.invite = orig
    assert called.get("invite") is True


@pytest.mark.asyncio
async def test_admin_button_overview_routes(conn):
    from english_tutor.handlers import menu as menu_h

    admin_id = 1
    db.upsert_student(conn, admin_id, status="active", level="B1")
    msg = FakeMessage(text="📊 Обзор", tg_id=admin_id)
    st = FakeState()
    called = {}

    async def fake_stats(message, conn, llm, admin_id):
        called["overview"] = True

    import english_tutor.handlers.admin as admin_h

    orig = admin_h.stats_cmd
    admin_h.stats_cmd = fake_stats
    try:
        await menu_h.btn_overview(msg, st, conn, admin_id, llm=None)
    finally:
        admin_h.stats_cmd = orig
    assert called.get("overview") is True


@pytest.mark.asyncio
async def test_admin_button_student_mode_switches_keyboard(conn):
    from english_tutor.handlers import menu as menu_h

    admin_id = 1
    db.upsert_student(conn, admin_id, status="active", level="B1")
    msg = FakeMessage(text="🧑‍🎓 Режим ученика", tg_id=admin_id)
    st = FakeState()
    await menu_h.btn_student_mode(msg, st)
    assert msg.reply_markup == learner_main_keyboard()


@pytest.mark.asyncio
async def test_non_admin_button_students_rejected(conn):
    from english_tutor.handlers import menu as menu_h

    msg = FakeMessage(text="👥 Студенты", tg_id=2)
    st = FakeState()
    await menu_h.btn_students(msg, st, conn, admin_id=1)
    assert "только для админа" in msg.sent[-1]
