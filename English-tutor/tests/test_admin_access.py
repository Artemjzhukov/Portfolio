
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
    await admin_handlers.invite(msg, conn, admin_id=ADMIN)
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


async def test_stats_requires_admin(conn):
    msg = FakeMsg("/stats", STRANGER)
    await admin_handlers.stats_cmd(msg, conn, llm=None, admin_id=ADMIN)
    assert "админ" in msg.sent[0].lower()


async def test_stats_overview_for_admin(conn):
    db.upsert_student(conn, 42, status="active", level="B1", name="Olya")
    msg = FakeMsg("/stats", ADMIN)
    await admin_handlers.stats_cmd(msg, conn, llm=None, admin_id=ADMIN)
    assert "Olya" in msg.sent[0] and "B1" in msg.sent[0]


async def test_stats_detail_shows_patterns(conn):
    db.upsert_student(conn, 42, status="active", level="B1", name="Olya")
    db.insert_correction(conn, 42, "I goed", "I went", "verb", source="chat")
    db.insert_correction(conn, 42, "I goed", "I went", "verb", source="chat")

    class LLM:
        async def chat_json_async(self, system, user):
            return {"items": [{"id": 1, "category": "tenses"},
                              {"id": 2, "category": "tenses"}]}

    msg = FakeMsg("/stats 42", ADMIN)
    await admin_handlers.stats_cmd(msg, conn, llm=LLM(), admin_id=ADMIN)
    text = "\n".join(msg.sent)
    assert "📊 Студент 42" in text and "Слабые места" in text
    assert "времена" in text and "частые ошибки" in text.lower()


async def test_mylevel_shows_level_and_hint(conn):
    from english_tutor.handlers import lessons as lessons_h

    db.upsert_student(conn, 42, status="active", level="B1")
    for topic in [
        "Present Perfect vs Past Simple", "Present Perfect Continuous",
        "Past Continuous and Narrative",
        "Future and Probability (will/going to, may/might, First Conditional)",
        "Passive Voice (present/past)",
    ]:
        cur = conn.execute(
            "INSERT INTO lessons (kind, level, topic, student_id, content_json) "
            "VALUES ('curriculum', 'B1', ?, NULL, '{}')",
            (topic,),
        )
        db.record_progress(conn, 42, cur.lastrowid, "completed", 3)
    conn.commit()
    msg = FakeMsg("/mylevel", 42)
    await lessons_h.mylevel_cmd(msg, None, conn)
    text = "\n".join(msg.sent)
    assert "B1" in text and "5/6" in text and "переаттестация" in text
