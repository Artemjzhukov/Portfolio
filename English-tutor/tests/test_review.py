import pytest

from english_tutor import db
from english_tutor.handlers import review as review_h
from english_tutor.services import srs


class FakeMessage:
    def __init__(self, text=None, tg_id=42, voice=None):
        self.text = text
        self.voice = voice
        self.from_user = type("U", (), {"id": tg_id})()
        self.sent = []
        self.bot = self

    async def answer(self, text):
        self.sent.append(text)

    async def download(self, *a, **k):
        raise AssertionError("download should be monkeypatched in tests")


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
def student(conn):
    db.upsert_student(conn, 42, status="active", level="B1")


@pytest.fixture
def st():
    return FakeState()


def _force_due(conn, word_en):
    from datetime import date

    conn.execute(
        "UPDATE srs_cards SET due_date=? WHERE word_en=?", (str(date.today()), word_en)
    )
    conn.commit()


async def test_review_requires_active_student(conn, st):
    msg = FakeMessage(text="/review")
    await review_h.review_cmd(msg, st, conn)
    assert "start" in msg.sent[-1].lower()


async def test_review_no_due_words(conn, st, student):
    msg = FakeMessage(text="/review")
    await review_h.review_cmd(msg, st, conn)
    assert "Дежурных слов нет" in msg.sent[0]
    assert st.state is None


async def test_review_full_cycle(conn, st, student):
    from datetime import date, timedelta

    srs.ensure_card(conn, 42, "cat", "кошка")
    srs.ensure_card(conn, 42, "dog", "собака")
    for word in ("cat", "dog"):
        conn.execute(
            "UPDATE srs_cards SET due_date=? WHERE word_en=?",
            (str(date.today() - timedelta(days=1)), word),
        )
    conn.commit()

    msg = FakeMessage(text="/review")
    await review_h.review_cmd(msg, st, conn)
    assert st.state == review_h.Review.active
    assert "кошка" in msg.sent[-1]

    ans1 = FakeMessage(text="cat")
    await review_h.review_flow(ans1, st, conn, None)
    assert any("✅" in t for t in ans1.sent)
    assert "собака" in ans1.sent[-1]  # next question asked

    ans2 = FakeMessage(text="wrong")
    await review_h.review_flow(ans2, st, conn, None)
    assert st.state is None
    assert any("Готово! 1/2" in t for t in ans2.sent)
    # ladder moved: cat correct → step 1; dog wrong → reset 0
    cat = conn.execute("SELECT * FROM srs_cards WHERE word_en='cat'").fetchone()
    dog = conn.execute("SELECT * FROM srs_cards WHERE word_en='dog'").fetchone()
    assert cat["interval_index"] == 1 and dog["interval_index"] == 0


async def test_review_voice_answer(conn, st, student, monkeypatch):
    from datetime import date, timedelta

    srs.ensure_card(conn, 42, "cat", "кошка")
    conn.execute(
        "UPDATE srs_cards SET due_date=? WHERE word_en='cat'",
        (str(date.today() - timedelta(days=1)),),
    )
    conn.commit()
    await review_h.review_cmd(FakeMessage(text="/review"), st, conn)

    import english_tutor.handlers.voice as voice_mod

    async def fake_transcribe(message, bot, llm):
        return "cat"

    monkeypatch.setattr(voice_mod, "save_and_transcribe", fake_transcribe)
    msg = FakeMessage(voice=type("V", (), {"duration": 5})())
    msg.text = None
    await review_h.review_flow(msg, st, conn, llm=None)
    assert any("✅" in t for t in msg.sent)
