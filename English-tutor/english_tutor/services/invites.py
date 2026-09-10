import random
import string

_ALPHABET = string.ascii_uppercase + string.digits


def new_code(rng: random.Random | None = None) -> str:
    r = rng or random
    return "TUTOR-" + "".join(r.choice(_ALPHABET) for _ in range(4))


def create_invite(conn, rng: random.Random | None = None) -> str:
    code = new_code(rng)
    conn.execute("INSERT INTO invite_codes (code) VALUES (?)", (code,))
    conn.commit()
    return code


def redeem(conn, code: str, tg_id: int) -> bool:
    code = code.strip().upper()
    row = conn.execute("SELECT used_by FROM invite_codes WHERE code=?", (code,)).fetchone()
    if row is None or row["used_by"] is not None:
        return False
    student = conn.execute("SELECT status FROM students WHERE tg_id=?", (tg_id,)).fetchone()
    if student is not None and student["status"] != "new":
        return False
    if student is None:
        conn.execute("INSERT INTO students (tg_id, status) VALUES (?, 'testing')", (tg_id,))
    else:
        conn.execute("UPDATE students SET status='testing' WHERE tg_id=?", (tg_id,))
    # atomic claim: only one caller can mark an unused code as used
    cur = conn.execute(
        "UPDATE invite_codes SET used_by=? WHERE code=? AND used_by IS NULL",
        (tg_id, code),
    )
    if cur.rowcount != 1:
        conn.rollback()  # lost the race — undo the student status change
        return False
    conn.commit()
    return True
