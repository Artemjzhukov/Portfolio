"""Тесты job store (SQLite) и идемпотентности."""

import json

import pytest

from app.jobs import STALE_SECONDS, JobStore, compute_job_id
from app.schemas import SubmissionInput


@pytest.fixture
def store(tmp_path):
    return JobStore(str(tmp_path / "jobs.db"))


class TestJobStore:
    def test_new_job_queued(self, store):
        reused, result = store.create(
            "j1", student_id="s", subject_id="history", submission_type="ege_exam", file_hash="h"
        )
        assert reused is False and result is None
        assert store.get("j1")["status"] == "queued"

    def test_lifecycle_running_done_with_result(self, store):
        store.create("j1", student_id="s", subject_id="h", submission_type="ege_exam", file_hash="h")
        store.set_running("j1")
        assert store.get("j1")["status"] == "running"
        store.set_done("j1", {"total_score": 3})
        row = store.get("j1")
        assert row["status"] == "done"
        assert json.loads(row["result_json"]) == {"total_score": 3}
        assert row["finished_at"] is not None

    def test_reuse_done_job_returns_result(self, store):
        store.create("j1", student_id="s", subject_id="h", submission_type="ege_exam", file_hash="h")
        store.set_done("j1", {"total_score": 3})
        reused, result = store.create(
            "j1", student_id="s", subject_id="h", submission_type="ege_exam", file_hash="h"
        )
        assert reused is True
        assert result == {"total_score": 3}

    def test_reuse_running_job_no_double_work(self, store):
        store.create("j1", student_id="s", subject_id="h", submission_type="ege_exam", file_hash="h")
        store.set_running("j1")
        reused, result = store.create(
            "j1", student_id="s", subject_id="h", submission_type="ege_exam", file_hash="h"
        )
        assert reused is True and result is None

    def test_error_job_is_requeued(self, store):
        store.create("j1", student_id="s", subject_id="h", submission_type="ege_exam", file_hash="h")
        store.set_error("j1", "LLM недоступна")
        reused, result = store.create(
            "j1", student_id="s", subject_id="h", submission_type="ege_exam", file_hash="h"
        )
        assert reused is False
        assert store.get("j1")["status"] == "queued"
        assert store.get("j1")["error"] is None

    def test_stale_running_job_is_reset(self, store):
        store.create("j1", student_id="s", subject_id="h", submission_type="ege_exam", file_hash="h")
        store.set_running("j1")
        # эмулируем зависшую джобу (процесс умер во время оценки)
        store._conn.execute("UPDATE jobs SET created_at = ? WHERE job_id = ?", (0.0, "j1"))
        store._conn.commit()
        reused, _ = store.create(
            "j1", student_id="s", subject_id="h", submission_type="ege_exam", file_hash="h"
        )
        assert reused is False
        assert store.get("j1")["status"] == "queued"


def make_payload(**kwargs):
    base = dict(
        file_bytes="AAAA",
        submission_type="standard_test",
        subject_id="history",
        student_id="s1",
        answer_key={"1": "3"},
    )
    base.update(kwargs)
    return SubmissionInput(**base)


class TestComputeJobId:
    def test_stable_for_same_input(self, settings):
        a = compute_job_id(make_payload(), b"bytes", settings)
        b = compute_job_id(make_payload(), b"bytes", settings)
        assert a == b

    def test_changes_with_file(self, settings):
        a = compute_job_id(make_payload(), b"bytes", settings)
        b = compute_job_id(make_payload(), b"other", settings)
        assert a != b

    def test_changes_with_answer_key(self, settings):
        a = compute_job_id(make_payload(), b"x", settings)
        b = compute_job_id(make_payload(answer_key={"1": "4"}), b"x", settings)
        assert a != b

    def test_changes_with_student(self, settings):
        a = compute_job_id(make_payload(), b"x", settings)
        b = compute_job_id(make_payload(student_id="s2"), b"x", settings)
        assert a != b

    def test_changes_with_rubric_content(self, settings, tmp_path):
        """Изменение файла рубрики инвалидирует кэш."""
        import shutil
        from pathlib import Path

        settings.criteria_dir = tmp_path / "criteria"
        (settings.criteria_dir / "history").mkdir(parents=True)
        src = settings.criteria_dir / "history" / "task_19.json"
        original = Path("data/criteria/history/task_19.json").read_text(encoding="utf-8")
        src.write_text(original, encoding="utf-8")

        payload = make_payload(submission_type="ege_exam")
        a = compute_job_id(payload, b"x", settings)
        src.write_text(original + "\n", encoding="utf-8")
        b = compute_job_id(payload, b"x", settings)
        assert a != b
