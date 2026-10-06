"""Тесты персистентности прогресса: таблицы results и dashboard_tokens в том же SQLite."""

import pytest

from app.jobs import JobStore
from app.schemas import AssessmentResult, EvaluationRecord, TaskBreakdown


@pytest.fixture
def store(tmp_path):
    return JobStore(str(tmp_path / "jobs.db"))


def make_record(job="j1", student="s1", evaluated_at=100.0, tasks=2, total=3, maximum=4):
    return EvaluationRecord(
        job_id=job,
        student_id=student,
        subject_id="history",
        submission_type="standard_test",
        test_title="Вариант 3",
        total_score=total,
        max_possible_score=maximum,
        percentage=0,
        task_breakdown=[
            TaskBreakdown(task_number=i, max_points=1, earned_points=1, status="Correct")
            for i in range(tasks)
        ],
        evaluated_at=evaluated_at,
    )


class TestResultsTable:
    def test_save_and_get_roundtrip(self, store):
        store.save_result(make_record())
        row = store.get_result_record("j1")
        assert row["job_id"] == "j1"
        assert row["test_title"] == "Вариант 3"
        assert row["task_breakdown"][1]["task_number"] == 1
        assert row["evaluated_at"] == 100.0

    def test_save_overwrites_same_job(self, store):
        store.save_result(make_record())
        store.save_result(make_record(total=1, maximum=1))
        assert store.get_result_record("j1")["total_score"] == 1.0

    def test_get_missing_returns_none(self, store):
        assert store.get_result_record("nope") is None

    def test_list_recent_limit_and_order(self, store):
        for i in range(12):
            store.save_result(make_record(job=f"j{i}", evaluated_at=100.0 + i))
        rows = store.list_recent("s1", limit=10)
        assert [r["job_id"] for r in rows] == [f"j{i}" for i in range(11, 1, -1)]
        assert store.count_results("s1") == 12

    def test_list_only_own_student(self, store):
        store.save_result(make_record(job="a", student="s1"))
        store.save_result(make_record(job="b", student="s2"))
        assert [r["job_id"] for r in store.list_recent("s1")] == ["a"]

    def test_from_assessment_matches_saved(self, store):
        result = AssessmentResult(
            student_id="s1", subject_id="history", submission_type="standard_test",
            total_score=3, max_possible_score=4, percentage=0, summary_feedback="s",
            task_breakdown=[TaskBreakdown(task_number=1, max_points=1, earned_points=0, status="Incorrect")],
        )
        store.save_result(EvaluationRecord.from_assessment("j9", result, evaluated_at=50.0))
        row = store.get_result_record("j9")
        assert row["percentage"] == 75.0
        assert row["task_breakdown"][0]["status"] == "Incorrect"


class TestDashboardTokens:
    def test_issue_returns_raw_but_stores_hash(self, store):
        raw = store.issue_token("s1", "42", now=100.0)
        assert isinstance(raw, str) and len(raw) >= 20
        rows = store._conn.execute("SELECT token_hash FROM dashboard_tokens").fetchall()
        assert len(rows) == 1
        assert rows[0][0] != raw
        assert len(rows[0][0]) == 64

    def test_consume_valid_marks_used(self, store):
        raw = store.issue_token("s1", "42", now=100.0)
        rec = store.consume_token(raw, "42", now=200.0)
        assert rec is not None and rec["student_id"] == "s1"
        assert store.consume_token(raw, "42", now=200.0) is None

    def test_consume_wrong_chat_rejected(self, store):
        raw = store.issue_token("s1", "42", now=100.0)
        assert store.consume_token(raw, "43", now=200.0) is None

    def test_consume_expired_rejected(self, store):
        raw = store.issue_token("s1", "42", ttl_hours=72, now=100.0)
        assert store.consume_token(raw, "42", now=100.0 + 72 * 3600 + 1) is None

    def test_consume_unknown_rejected(self, store):
        assert store.consume_token("x" * 32, "42", now=1.0) is None

    def test_revoke_invalidates_old_tokens(self, store):
        raw = store.issue_token("s1", "42", now=100.0)
        store.revoke_tokens("s1", "42")
        assert store.consume_token(raw, "42", now=200.0) is None
        fresh = store.issue_token("s1", "42", now=200.0)
        assert store.consume_token(fresh, "42", now=300.0) is not None
