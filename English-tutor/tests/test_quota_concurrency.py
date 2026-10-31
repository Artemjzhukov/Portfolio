import threading

from english_tutor import db
from english_tutor.services import limits


def _conn(path):
    c = db.connect(str(path))
    c.execute("PRAGMA busy_timeout=30000")
    return c


def test_material_quota_exact_five(tmp_path):
    path = tmp_path / "t.db"
    c = _conn(path)
    db.upsert_student(c, 1, status="active", level="A2")
    for i in range(5):
        assert limits.try_reserve_material_analysis(c, 1) is True
    assert limits.try_reserve_material_analysis(c, 1) is False
    assert limits.material_analyses_left(c, 1) == 0
    c.close()


def test_material_quota_no_increment_on_fail(tmp_path):
    path = tmp_path / "t.db"
    c = _conn(path)
    db.upsert_student(c, 1, status="active", level="A2")
    for _ in range(5):
        limits.try_reserve_material_analysis(c, 1)
    before = c.execute("SELECT material_calls FROM daily_usage WHERE student_id=1").fetchone()[0]
    assert limits.try_reserve_material_analysis(c, 1) is False
    after = c.execute("SELECT material_calls FROM daily_usage WHERE student_id=1").fetchone()[0]
    assert before == after == 5
    c.close()


def test_material_quota_concurrent(tmp_path):
    path = tmp_path / "t.db"
    c0 = _conn(path)
    db.upsert_student(c0, 1, status="active", level="A2")
    c0.close()

    results = []
    lock = threading.Lock()

    def worker():
        c = _conn(path)
        db.upsert_student(c, 1, status="active", level="A2")
        r = limits.try_reserve_material_analysis(c, 1)
        with lock:
            results.append(r)
        c.close()

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(1 for r in results if r) == 5
    c = _conn(path)
    assert c.execute("SELECT material_calls FROM daily_usage WHERE student_id=1").fetchone()[0] == 5
    c.close()


def test_llm_quota_boundary(tmp_path):
    path = tmp_path / "t.db"
    c = _conn(path)
    db.upsert_student(c, 1, status="active", level="A2")
    # use small limit by monkeypatch? Instead test via try_reserve until fail
    # We won't exhaust 200; just check increment
    assert limits.try_reserve_llm(c, 1) is True
    assert limits.daily_left(c, 1) == 199
    c.close()


def test_llm_quota_concurrent(tmp_path):
    path = tmp_path / "t.db"
    c0 = _conn(path)
    db.upsert_student(c0, 1, status="active", level="A2")
    c0.close()

    results = []
    lock = threading.Lock()

    def worker():
        c = _conn(path)
        db.upsert_student(c, 1, status="active", level="A2")
        r = limits.try_reserve_llm(c, 1)
        with lock:
            results.append(r)
        c.close()

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(1 for r in results if r) <= 200
    c = _conn(path)
    used = c.execute("SELECT llm_calls FROM daily_usage WHERE student_id=1").fetchone()[0]
    assert used == sum(1 for r in results if r)
    c.close()
