import pytest

from english_tutor import db
from english_tutor.handlers import review as review_h
from english_tutor.services import srs


class FakeMessage:
    def __init__(self, text=None, tg_id=42):
        self.text = text
        self.voice = None
        self.from_user = type("U", (), {"id": tg_id})()
        self.sent = []
        self.bot = self

    async def answer(self, text, **kw):
        self.sent.append(text)


class FakeState:
    def __init__(self):
        self.state = None
        self.data = {}

    async def set_state(self, s):
        self.state = s

    async def update_data(self, **kw):
        self.data.update(kw)

    async def get_data(self):
        return dict(self.data)

    async def clear(self):
        self.state = None
        self.data = {}


@pytest.mark.asyncio
async def test_reviewmaterial_command_reaches_handler(conn):
    db.upsert_student(conn, 42, status="active", level="B1")
    mid = db.save_material(conn, 42, "h", "text", "Title", "{}")
    db.save_material_items(conn, mid, [{"type": "word", "en": "cat", "ru": "кошка"}])
    srs.ensure_card(conn, 42, "cat", "кошка", material_id=mid)
    conn.execute("UPDATE srs_cards SET due_date='2020-01-01' WHERE student_id=42")
    conn.commit()
    msg = FakeMessage(text="/reviewmaterial", tg_id=42)
    st = FakeState()
    await review_h.review_material_cmd(msg, st, conn)
    assert st.state == review_h.MaterialSelect.active
    assert msg.sent


@pytest.mark.asyncio
async def test_reviewmaterial_not_blocked_by_quota(conn):
    db.upsert_student(conn, 42, status="active", level="B1")
    mid = db.save_material(conn, 42, "h", "text", "Title", "{}")
    db.save_material_items(conn, mid, [{"type": "word", "en": "cat", "ru": "кошка"}])
    srs.ensure_card(conn, 42, "cat", "кошка", material_id=mid)
    conn.execute("UPDATE srs_cards SET due_date='2020-01-01' WHERE student_id=42")
    conn.commit()
    # exhaust material quota
    from english_tutor.services import limits

    for _ in range(5):
        limits.try_reserve_material_analysis(conn, 42)
    msg = FakeMessage(text="/reviewmaterial", tg_id=42)
    st = FakeState()
    await review_h.review_material_cmd(msg, st, conn)
    assert st.state == review_h.MaterialSelect.active


@pytest.mark.asyncio
async def test_reviewmaterial_empty(conn):
    db.upsert_student(conn, 42, status="active", level="B1")
    msg = FakeMessage(text="/reviewmaterial", tg_id=42)
    st = FakeState()
    await review_h.review_material_cmd(msg, st, conn)
    assert "Нет материалов" in msg.sent[0]
