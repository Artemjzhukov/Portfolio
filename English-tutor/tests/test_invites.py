import random

from english_tutor import db
from english_tutor.services import invites


def test_new_code_format():
    code = invites.new_code(random.Random(1))
    assert len(code) == 10 and code.startswith("TUTOR-")
    assert code[6:].isalnum() and code[6:].isupper()


def test_new_code_deterministic_with_rng():
    assert invites.new_code(random.Random(5)) == invites.new_code(random.Random(5))


def test_create_and_redeem(conn):
    code = invites.create_invite(conn)
    db.upsert_student(conn, 42)
    assert invites.redeem(conn, code, 42) is True
    row = conn.execute("SELECT used_by FROM invite_codes WHERE code=?", (code,)).fetchone()
    assert row["used_by"] == 42
    assert db.get_student(conn, 42)["status"] == "testing"


def test_redeem_creates_student_if_missing(conn):
    code = invites.create_invite(conn)
    assert invites.redeem(conn, code, 77) is True
    assert db.get_student(conn, 77)["status"] == "testing"


def test_redeem_twice_fails(conn):
    code = invites.create_invite(conn)
    db.upsert_student(conn, 42)
    assert invites.redeem(conn, code, 42) is True
    assert invites.redeem(conn, code, 43) is False


def test_redeem_unknown_code_fails(conn):
    assert invites.redeem(conn, "TUTOR-XXXX", 1) is False
