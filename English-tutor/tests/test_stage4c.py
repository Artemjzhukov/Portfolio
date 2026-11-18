import pytest

from english_tutor import db
from english_tutor.handlers import materials as materials_h
from english_tutor.handlers import review as review_h
from english_tutor.services import srs


class FakeMessage:
    def __init__(self, text=None, tg_id=42, voice=None):
        self.text = text
        self.voice = voice
        self.from_user = type("U", (), {"id": tg_id})()
        self.sent = []
        self.bot = self

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


class FakeCallback:
    def __init__(self, data, tg_id=42):
        self.data = data
        self.from_user = type("U", (), {"id": tg_id})()
        self.message = FakeMessage(tg_id=tg_id)
        self.answered = 0

    async def answer(self, *a, **kw):
        self.answered += 1


@pytest.fixture
def st():
    return FakeState()


async def test_reviewmaterial_filters_by_material(conn, st):
    db.upsert_student(conn, 42, status="active", level="B1")
    db.upsert_student(conn, 7, status="active", level="B1")
    mid = db.save_material(conn, 42, "h1", "text", "Title", "{}")
    db.save_material_items(conn, mid, [{"type": "word", "en": "cat", "ru": "кошка"}])
    srs.ensure_card(conn, 42, "cat", "кошка", material_id=mid)
    # due
    conn.execute("UPDATE srs_cards SET due_date='2020-01-01' WHERE student_id=42")
    conn.commit()
    # other student material
    mid2 = db.save_material(conn, 7, "h2", "text2", "T2", "{}")
    db.save_material_items(conn, mid2, [{"type": "word", "en": "dog", "ru": "собака"}])
    srs.ensure_card(conn, 7, "dog", "собака", material_id=mid2)
    conn.execute("UPDATE srs_cards SET due_date='2020-01-01' WHERE student_id=7")
    conn.commit()

    msg = FakeMessage(text="/reviewmaterial", tg_id=42)
    await review_h.review_material_cmd(msg, st, conn)
    assert st.state == review_h.MaterialSelect.active
    # select first
    msg2 = FakeMessage(text="1", tg_id=42)
    await review_h.review_material_select(msg2, st, conn)
    assert st.state == review_h.Review.active
    assert st.data["card_ids"]
    card = srs.get_card(conn, st.data["card_ids"][0])
    assert card["word_en"] == "cat"


async def test_reviewmaterial_empty(conn, st):
    db.upsert_student(conn, 42, status="active", level="B1")
    msg = FakeMessage(text="/reviewmaterial", tg_id=42)
    await review_h.review_material_cmd(msg, st, conn)
    assert "Нет материалов" in msg.sent[0]
    assert st.state is None


async def test_review_suggests_material_review(conn, st):
    db.upsert_student(conn, 42, status="active", level="B1")
    mid = db.save_material(conn, 42, "h1", "text", "Title", "{}")
    db.save_material_items(conn, mid, [{"type": "word", "en": "cat", "ru": "кошка"}])
    srs.ensure_card(conn, 42, "cat", "кошка", material_id=mid)
    from datetime import date, timedelta

    due = str(date.today() - timedelta(days=1))
    conn.execute("UPDATE srs_cards SET due_date=? WHERE word_en='cat'", (due,))
    conn.commit()
    # also a global due card
    srs.ensure_card(conn, 42, "dog", "собака")
    conn.execute("UPDATE srs_cards SET due_date=? WHERE word_en='dog'", (due,))
    conn.commit()
    msg = FakeMessage(text="/review", tg_id=42)
    await review_h.review_cmd(msg, st, conn)
    assert any("reviewmaterial" in t for t in msg.sent)


async def test_review_no_suggestion_without_material_cards(conn, st):
    db.upsert_student(conn, 42, status="active", level="B1")
    srs.ensure_card(conn, 42, "dog", "собака")
    from datetime import date, timedelta

    due = str(date.today() - timedelta(days=1))
    conn.execute("UPDATE srs_cards SET due_date=? WHERE word_en='dog'", (due,))
    conn.commit()
    msg = FakeMessage(text="/review", tg_id=42)
    await review_h.review_cmd(msg, st, conn)
    assert not any("reviewmaterial" in t for t in msg.sent)


async def test_material_exercise_done_reports_total(conn, st):
    """`mat:ex:done` must report the queue length loaded from FSM storage.

    Regression: the handler referenced a local `queue` variable that only
    existed in the sibling branch, raising NameError after clearing the
    session, so the student never saw the result summary.
    """
    db.upsert_student(conn, 42, status="active", level="B1")
    await st.update_data(
        analysis={"title": "T"},
        correct=1,
        exercise_queue=[
            {"type": "translation", "item": {"en": "cat", "ru": "кошка"}},
            {"type": "spelling", "item": {"en": "dog", "ru": "собака"}},
        ],
    )
    cb = FakeCallback("mat:ex:done")
    await materials_h.cb_exercise(cb, st, conn)

    assert any("Готово! Верно: 1/2." in t for t in cb.message.sent)
    assert st.state is None
    assert cb.answered == 1
