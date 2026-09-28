from english_tutor import db


def test_connect_creates_schema(conn):
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"students", "invite_codes", "test_results", "lessons",
            "lesson_progress", "corrections", "srs_cards", "stories", "story_progress"} <= tables


def test_save_and_get_story(conn):
    db.upsert_student(conn, 42, status="active", level="A2")
    story_id = db.save_story(conn, 42, "A2", "coffee", '{"title": "Coffee Time"}')
    assert story_id > 0
    row = db.get_story(conn, story_id)
    assert row["level"] == "A2"
    assert row["topic"] == "coffee"
    assert "Coffee Time" in row["content_json"]


def test_record_story_progress(conn):
    db.upsert_student(conn, 42, status="active", level="A2")
    story_id = db.save_story(conn, 42, "A2", "trip", '{"title": "Trip"}')
    pid = db.record_story_progress(
        conn, 42, story_id, questions_score=2,
        retell_transcript="I went to trip", retell_passed=True,
    )
    assert pid > 0
    row = conn.execute("SELECT * FROM story_progress WHERE id=?", (pid,)).fetchone()
    assert row["student_id"] == 42
    assert row["questions_score"] == 2
    assert row["retell_passed"] == 1



def test_upsert_and_get_student(conn):
    db.upsert_student(conn, 42, name="Olya", status="testing")
    s = db.get_student(conn, 42)
    assert (s["tg_id"], s["name"], s["status"], s["level"]) == (42, "Olya", "testing", None)


def test_upsert_updates_existing(conn):
    db.upsert_student(conn, 42, name="Olya")
    db.upsert_student(conn, 42, name="Olga", status="active", level="B1")
    s = db.get_student(conn, 42)
    assert (s["name"], s["status"], s["level"]) == ("Olga", "active", "B1")


def test_set_status_and_level(conn):
    db.upsert_student(conn, 7)
    db.set_student_status(conn, 7, "active")
    db.set_student_level(conn, 7, "A2")
    s = db.get_student(conn, 7)
    assert (s["status"], s["level"]) == ("active", "A2")


def test_list_students_by_status(conn):
    db.upsert_student(conn, 1, status="pending")
    db.upsert_student(conn, 2, status="active")
    assert [r["tg_id"] for r in db.list_students(conn, "pending")] == [1]
    assert len(db.list_students(conn)) == 2


def test_get_missing_student(conn):
    assert db.get_student(conn, 999) is None


def test_save_test_result(conn):
    db.upsert_student(conn, 5, status="testing")
    db.save_test_result(conn, 5, written_score=13, voice_transcript="my day...", suggested_level="B1")
    row = conn.execute("SELECT * FROM test_results WHERE student_id=5").fetchone()
    assert (row["written_score"], row["suggested_level"]) == (13, "B1")
