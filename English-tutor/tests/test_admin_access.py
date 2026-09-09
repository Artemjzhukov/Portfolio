import pytest

from english_tutor import db
from english_tutor.handlers import admin as admin_handlers


class FakeMsg:
    def __init__(self, text, tg_id):
        self.text = text
        self.from_user = type("U", (), {"id": tg_id})()
        self.sent = []

    async def answer(self, text):
        self.sent.append(text)


ADMIN, STRANGER = 99, 7


async def test_invite_rejected_for_non_admin(conn):
    msg = FakeMsg("/invite", STRANGER)
    await admin_handlers.invite(msg, conn)
    assert "админ" in msg.sent[0].lower()
    assert conn.execute("SELECT COUNT(*) c FROM invite_codes").fetchone()["c"] == 0


async def test_invite_works_for_admin(conn):
    msg = FakeMsg("/invite", ADMIN)
    await admin_handlers.invite(msg, conn, admin_id=ADMIN)
    assert "TUTOR-" in msg.sent[0]


async def test_approve_rejected_for_non_admin(conn):
    msg = FakeMsg("/approve 42", STRANGER)
    await admin_handlers.approve(msg, conn, admin_id=ADMIN)
    assert "админ" in msg.sent[0].lower()
    assert db.get_student(conn, 42) is None


async def test_students_rejected_for_non_admin(conn):
    msg = FakeMsg("/students", STRANGER)
    await admin_handlers.students(msg, conn, admin_id=ADMIN)
    assert "админ" in msg.sent[0].lower()
