import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    tg_id INTEGER PRIMARY KEY,
    name TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    level TEXT,
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
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(kind, level, topic, student_id)
);
CREATE TABLE IF NOT EXISTS lesson_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(tg_id),
    lesson_id INTEGER NOT NULL REFERENCES lessons(id),
    status TEXT NOT NULL DEFAULT 'in_progress',
    score INTEGER
);
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
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def get_student(conn, tg_id):
    return conn.execute("SELECT * FROM students WHERE tg_id=?", (tg_id,)).fetchone()


def upsert_student(conn, tg_id, name=None, status=None, level=None):
    conn.execute(
        "INSERT INTO students (tg_id, name, status) VALUES (?, ?, COALESCE(?, 'new')) "
        "ON CONFLICT(tg_id) DO UPDATE SET name=COALESCE(excluded.name, name), "
        "status=COALESCE(?, status), level=COALESCE(?, level)",
        (tg_id, name, status, status, level),
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
