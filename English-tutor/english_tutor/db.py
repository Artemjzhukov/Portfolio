import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    tg_id INTEGER PRIMARY KEY,
    name TEXT,
    status TEXT NOT NULL DEFAULT 'new'
        CHECK (status IN ('new', 'testing', 'pending', 'active', 'blocked')),
    level TEXT CHECK (level IS NULL OR level IN ('A2', 'B1', 'B2')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS invite_codes (
    code TEXT PRIMARY KEY,
    used_by INTEGER REFERENCES students(tg_id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS test_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(tg_id),
    written_score INTEGER,
    voice_transcript TEXT,
    suggested_level TEXT
);
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    level TEXT NOT NULL,
    topic TEXT NOT NULL,
    student_id INTEGER REFERENCES students(tg_id),
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_lessons_shared
    ON lessons (kind, level, topic) WHERE student_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_lessons_personal
    ON lessons (kind, level, topic, student_id) WHERE student_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS lesson_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(tg_id),
    lesson_id INTEGER NOT NULL REFERENCES lessons(id),
    status TEXT NOT NULL DEFAULT 'in_progress',
    score INTEGER,
    completed_at TEXT NOT NULL DEFAULT (datetime('now'))
);
-- deferred to Phase 2: lesson_progress is not written yet (owner decision K2).
CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(tg_id),
    wrong TEXT,
    right TEXT,
    hint_ru TEXT,
    source TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS srs_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(tg_id),
    word_en TEXT NOT NULL,
    word_ru TEXT NOT NULL,
    interval_index INTEGER NOT NULL DEFAULT 0,
    due_date TEXT NOT NULL,
    UNIQUE(student_id, word_en)
);
CREATE TABLE IF NOT EXISTS daily_usage (
    student_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    llm_calls INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (student_id, day)
);
CREATE TABLE IF NOT EXISTS reminder_log (
    student_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    slot TEXT NOT NULL,
    PRIMARY KEY (student_id, day, slot)
);
CREATE TABLE IF NOT EXISTS srs_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(tg_id),
    card_id INTEGER NOT NULL REFERENCES srs_cards(id),
    day TEXT NOT NULL,
    correct INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS stories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER REFERENCES students(tg_id),
    level TEXT NOT NULL,
    topic TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS story_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(tg_id),
    story_id INTEGER NOT NULL REFERENCES stories(id),
    questions_score INTEGER NOT NULL,
    retell_transcript TEXT,
    retell_passed INTEGER NOT NULL DEFAULT 1,
    completed_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS active_story_sessions (
    student_id INTEGER PRIMARY KEY REFERENCES students(tg_id),
    story_id INTEGER NOT NULL REFERENCES stories(id),
    stage TEXT NOT NULL CHECK (stage IN ('answering_questions', 'waiting_retell')),
    q_idx INTEGER NOT NULL DEFAULT 0,
    correct INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(tg_id),
    source_hash TEXT NOT NULL,
    source_text TEXT NOT NULL,
    title TEXT,
    analysis_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(student_id, source_hash)
);
CREATE TABLE IF NOT EXISTS material_items (

    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    item_type TEXT NOT NULL CHECK (item_type IN ('phrase','term','word')),
    en TEXT NOT NULL,
    ru TEXT NOT NULL,
    item_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_material_items_material ON material_items(material_id);
CREATE INDEX IF NOT EXISTS idx_materials_student_hash ON materials(student_id, source_hash);
"""



def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn):
    """Add columns to tables created by older versions (idempotent)."""
    corrections_cols = {r["name"] for r in conn.execute("PRAGMA table_info(corrections)")}
    if "category" not in corrections_cols:
        conn.execute("ALTER TABLE corrections ADD COLUMN category TEXT")
    progress_cols = {r["name"] for r in conn.execute("PRAGMA table_info(lesson_progress)")}
    if "completed_at" not in progress_cols:
        conn.execute("ALTER TABLE lesson_progress ADD COLUMN completed_at TEXT")
    daily_cols = {r["name"] for r in conn.execute("PRAGMA table_info(daily_usage)")}
    if "material_calls" not in daily_cols:
        conn.execute("ALTER TABLE daily_usage ADD COLUMN material_calls INTEGER NOT NULL DEFAULT 0")
    srs_cols = {r["name"] for r in conn.execute("PRAGMA table_info(srs_cards)")}
    if "material_id" not in srs_cols:
        conn.execute("ALTER TABLE srs_cards ADD COLUMN material_id INTEGER REFERENCES materials(id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_srs_cards_material ON srs_cards(material_id)")
    conn.commit()


def get_student(conn, tg_id):
    return conn.execute("SELECT * FROM students WHERE tg_id=?", (tg_id,)).fetchone()


def upsert_student(conn, tg_id, name=None, status=None, level=None):
    conn.execute(
        "INSERT INTO students (tg_id, name, status, level) "
        "VALUES (?, ?, COALESCE(?, 'new'), ?) "
        "ON CONFLICT(tg_id) DO UPDATE SET name=COALESCE(excluded.name, name), "
        "status=COALESCE(?, status), level=COALESCE(excluded.level, level)",
        (tg_id, name, status, level, status),
    )
    conn.commit()


def set_student_status(conn, tg_id, status):
    conn.execute("UPDATE students SET status=? WHERE tg_id=?", (status, tg_id))
    conn.commit()


def set_student_level(conn, tg_id, level):
    conn.execute("UPDATE students SET level=? WHERE tg_id=?", (level, tg_id))
    conn.commit()


def list_students(conn, status=None):
    if status is None:
        return conn.execute("SELECT * FROM students ORDER BY tg_id").fetchall()
    return conn.execute(
        "SELECT * FROM students WHERE status=? ORDER BY tg_id", (status,)
    ).fetchall()


def save_test_result(conn, student_id, written_score, voice_transcript, suggested_level):
    conn.execute(
        "INSERT INTO test_results (student_id, written_score, voice_transcript, suggested_level) "
        "VALUES (?, ?, ?, ?)",
        (student_id, written_score, voice_transcript, suggested_level),
    )
    conn.commit()


def insert_correction(conn, student_id, wrong, right, hint_ru, source="chat"):
    conn.execute(
        "INSERT INTO corrections (student_id, wrong, right, hint_ru, source) "
        "VALUES (?, ?, ?, ?, ?)",
        (student_id, wrong, right, hint_ru, source),
    )
    conn.commit()


def record_progress(conn, student_id, lesson_id, status="completed", score=None):
    conn.execute(
        "INSERT INTO lesson_progress (student_id, lesson_id, status, score, completed_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        (student_id, lesson_id, status, score),
    )
    conn.commit()

def save_material(conn, student_id, source_hash, source_text, title, analysis_json):
    cur = conn.execute(
        "INSERT INTO materials (student_id, source_hash, source_text, title, analysis_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (student_id, source_hash, source_text, title, analysis_json),
    )
    conn.commit()
    return cur.lastrowid

def get_material_by_hash(conn, student_id, source_hash):
    return conn.execute(
        "SELECT * FROM materials WHERE student_id=? AND source_hash=?", (student_id, source_hash)
    ).fetchone()

def get_material(conn, material_id):
    return conn.execute("SELECT * FROM materials WHERE id=?", (material_id,)).fetchone()

def list_materials(conn, student_id):
    return conn.execute(
        "SELECT * FROM materials WHERE student_id=? ORDER BY created_at DESC", (student_id,)
    ).fetchall()

def save_material_items(conn, material_id, items):
    ids = []
    for order, item in enumerate(items):
        cur = conn.execute(
            "INSERT INTO material_items (material_id, item_type, en, ru, item_order) "
            "VALUES (?, ?, ?, ?, ?)",
            (material_id, item["type"], item["en"].strip(), item["ru"].strip(), order),
        )
        ids.append(cur.lastrowid)
    conn.commit()
    return ids

def get_material_items(conn, material_id, item_type=None):
    if item_type:
        return conn.execute(
            "SELECT * FROM material_items WHERE material_id=? AND item_type=? ORDER BY item_order",
            (material_id, item_type),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM material_items WHERE material_id=? ORDER BY item_order", (material_id,)
    ).fetchall()


def log_review(conn, student_id, card_id, correct: bool, day=None):
    import os
    from datetime import datetime
    from zoneinfo import ZoneInfo

    if day is None:
        try:
            from english_tutor.config import load_config
            cfg = load_config()
            tz = ZoneInfo(cfg.tz)
        except Exception:
            tz = ZoneInfo(os.environ.get("TZ", "Europe/Kiev"))
        day = datetime.now(tz).strftime("%Y-%m-%d")

    conn.execute(
        "INSERT INTO srs_reviews (student_id, card_id, day, correct) VALUES (?, ?, ?, ?)",
        (student_id, card_id, day, 1 if correct else 0),
    )
    conn.commit()


def reminder_sent(conn, student_id, day, slot) -> bool:
    return conn.execute(
        "SELECT 1 FROM reminder_log WHERE student_id=? AND day=? AND slot=?",
        (student_id, day, slot),
    ).fetchone() is not None


def mark_reminder_sent(conn, student_id, day, slot):
    conn.execute(
        "INSERT OR IGNORE INTO reminder_log (student_id, day, slot) VALUES (?, ?, ?)",
        (student_id, day, slot),
    )
    conn.commit()


def save_story(conn, student_id: int | None, level: str, topic: str, content_json: str) -> int:
    cur = conn.execute(
        "INSERT INTO stories (student_id, level, topic, content_json) VALUES (?, ?, ?, ?)",
        (student_id, level, topic, content_json),
    )
    conn.commit()
    return cur.lastrowid


def get_story(conn, story_id: int):
    return conn.execute("SELECT * FROM stories WHERE id=?", (story_id,)).fetchone()


def record_story_progress(conn, student_id: int, story_id: int, questions_score: int,
                          retell_transcript: str, retell_passed: bool = True):
    cur = conn.execute(
        "INSERT INTO story_progress "
        "(student_id, story_id, questions_score, retell_transcript, retell_passed) "
        "VALUES (?, ?, ?, ?, ?)",
        (student_id, story_id, questions_score, retell_transcript, 1 if retell_passed else 0),
    )
    conn.commit()
    return cur.lastrowid


def complete_story(conn, student_id: int, story_id: int, questions_score: int,
                   retell_transcript: str, retell_passed: bool, glossary: list[dict]):
    """Atomically record story completion and create SRS cards from glossary.

    All writes - the ``story_progress`` INSERT plus every ``srs_cards`` INSERT
    derived from the glossary - plus removal of the active-session row, all
    succeed together or roll back together under a single ``with conn``
    transaction.  Network calls (Groq/Whisper) must happen *before* this
    function is called; only DB writes are enclosed here, keeping the
    transaction short and free of I/O.
    """
    from datetime import date, timedelta

    due = str(date.today() + timedelta(days=1))
    with conn:
        cur = conn.execute(
            "INSERT INTO story_progress "
            "(student_id, story_id, questions_score, retell_transcript, retell_passed) "
            "VALUES (?, ?, ?, ?, ?)",
            (student_id, story_id, questions_score, retell_transcript,
             1 if retell_passed else 0),
        )
        for item in glossary:
            conn.execute(
                "INSERT OR IGNORE INTO srs_cards "
                "(student_id, word_en, word_ru, interval_index, due_date) "
                "VALUES (?, ?, ?, 0, ?)",
                (student_id, item["en"].strip(), item["ru"].strip(), due),
            )
        conn.execute(
            "DELETE FROM active_story_sessions WHERE student_id=? AND story_id=?",
            (student_id, story_id),
        )
        return cur.lastrowid


def save_story_session(conn, student_id: int, story_id: int, stage: str,
                      q_idx: int = 0, correct: int = 0):
    """Insert or update the active story session for a student (upsert).

    At most one active session per student is enforced by the PRIMARY KEY
    on ``student_id`` - a second ``/story`` or ``/resume`` replaces the old
    row.
    """
    conn.execute(
        "INSERT INTO active_story_sessions "
        "(student_id, story_id, stage, q_idx, correct, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now')) "
        "ON CONFLICT(student_id) DO UPDATE SET "
        "story_id=excluded.story_id, stage=excluded.stage, "
        "q_idx=excluded.q_idx, correct=excluded.correct, "
        "updated_at=datetime('now')",
        (student_id, story_id, stage, q_idx, correct),
    )
    conn.commit()


def get_active_session(conn, student_id: int):
    """Return the active session row for a student, or None."""
    return conn.execute(
        "SELECT * FROM active_story_sessions WHERE student_id=?",
        (student_id,),
    ).fetchone()


def delete_active_session(conn, student_id: int):
    """Remove the active session for a student (used by /cancel and /resume-on-conflict)."""
    conn.execute(
        "DELETE FROM active_story_sessions WHERE student_id=?",
        (student_id,),
    )
    conn.commit()



def bump_usage(conn, student_id, day: str | None = None) -> int:
    from datetime import datetime, timezone

    day = day or datetime.now(timezone.utc).date().isoformat()
    conn.execute(
        "INSERT INTO daily_usage (student_id, day, llm_calls) VALUES (?, ?, 1) "
        "ON CONFLICT(student_id, day) DO UPDATE SET llm_calls = llm_calls + 1",
        (student_id, day),
    )
    conn.commit()
    row = conn.execute(
        "SELECT llm_calls FROM daily_usage WHERE student_id=? AND day=?",
        (student_id, day),
    ).fetchone()
    return row["llm_calls"]

