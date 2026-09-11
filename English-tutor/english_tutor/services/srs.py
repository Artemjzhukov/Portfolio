from datetime import date, timedelta

INTERVALS = [1, 3, 7, 14, 30]
DEFAULT_BATCH = 10


def ensure_card(conn, tg_id, word_en, word_ru) -> bool:
    """Add a word to the learner's deck. Returns True if a new card was created."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO srs_cards (student_id, word_en, word_ru, interval_index, due_date) "
        "VALUES (?, ?, ?, 0, ?)",
        (tg_id, word_en.strip(), word_ru.strip(), str(date.today() + timedelta(days=1))),
    )
    conn.commit()
    return cur.rowcount == 1


def due_cards(conn, tg_id, limit: int = DEFAULT_BATCH):
    return conn.execute(
        "SELECT * FROM srs_cards WHERE student_id=? AND due_date<=? ORDER BY due_date LIMIT ?",
        (tg_id, str(date.today()), limit),
    ).fetchall()


def get_card(conn, card_id):
    return conn.execute("SELECT * FROM srs_cards WHERE id=?", (card_id,)).fetchone()


def answer_card(conn, card_id, correct: bool):
    row = conn.execute("SELECT interval_index FROM srs_cards WHERE id=?", (card_id,)).fetchone()
    if row is None:
        return None
    idx = row["interval_index"]
    if correct:
        idx = min(idx + 1, len(INTERVALS) - 1)
    else:
        idx = 0
    due = str(date.today() + timedelta(days=INTERVALS[idx]))
    conn.execute(
        "UPDATE srs_cards SET interval_index=?, due_date=? WHERE id=?", (idx, due, card_id)
    )
    conn.commit()
    return INTERVALS[idx]


def format_question(card) -> str:
    return f"Как по-английски: «{card['word_ru']}»?"


def format_feedback(card, correct: bool) -> str:
    if correct:
        return f"✅ Верно! {card['word_en']}"
    return f"❌ Правильный ответ: {card['word_en']}"
