import pytest

from english_tutor import db


def test_invalid_status_rejected(conn):
    with pytest.raises(Exception):
        conn.execute("INSERT INTO students (tg_id, status) VALUES (1, 'superman')")


def test_invalid_level_rejected(conn):
    with pytest.raises(Exception):
        conn.execute("INSERT INTO students (tg_id, status, level) VALUES (1, 'new', 'Z9')")


def test_shared_lesson_dedup_via_partial_index(conn):
    conn.execute(
        "INSERT INTO lessons (kind, level, topic, student_id, content_json) "
        "VALUES ('curriculum', 'A2', 't', NULL, '{}')"
    )
    with pytest.raises(Exception):
        conn.execute(
            "INSERT INTO lessons (kind, level, topic, student_id, content_json) "
            "VALUES ('curriculum', 'A2', 't', NULL, '{}')"
        )


def test_personal_lesson_dedup_isolated_per_student(conn):
    db.upsert_student(conn, 1)
    db.upsert_student(conn, 2)
    conn.execute(
        "INSERT INTO lessons (kind, level, topic, student_id, content_json) "
        "VALUES ('theme', 'A2', 'cook', 1, '{}')"
    )
    with pytest.raises(Exception):
        conn.execute(
            "INSERT INTO lessons (kind, level, topic, student_id, content_json) "
            "VALUES ('theme', 'A2', 'cook', 1, '{}')"
        )
    # another student may have their own personal lesson with the same topic
    conn.execute(
        "INSERT INTO lessons (kind, level, topic, student_id, content_json) "
        "VALUES ('theme', 'A2', 'cook', 2, '{}')"
    )


def test_create_invite_retries_on_collision(conn, monkeypatch):
    from english_tutor.services import invites as inv

    conn.execute("INSERT INTO invite_codes (code) VALUES ('TUTOR-AAAA')")
    conn.commit()
    codes = iter(["TUTOR-AAAA", "TUTOR-BBBB"])
    monkeypatch.setattr(inv, "new_code", lambda rng=None: next(codes))
    assert inv.create_invite(conn) == "TUTOR-BBBB"


def test_create_invite_gives_up_after_max_retries(conn, monkeypatch):
    from english_tutor.services import invites as inv

    conn.execute("INSERT INTO invite_codes (code) VALUES ('TUTOR-AAAA')")
    conn.commit()
    monkeypatch.setattr(inv, "new_code", lambda rng=None: "TUTOR-AAAA")
    with pytest.raises(RuntimeError):
        inv.create_invite(conn)
