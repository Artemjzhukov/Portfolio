"""Тесты фасада evaluator.py: делегирование существующему пайплайну + сохранение прогресса."""

import pytest

from app.schemas import AssessmentResult, EvaluationRecord, TaskBreakdown


def make_assessment(student="s1", total=3.0, maximum=4.0):
    return AssessmentResult(
        student_id=student, subject_id="history", submission_type="standard_test",
        total_score=total, max_possible_score=maximum, percentage=0,
        summary_feedback="готово",
        task_breakdown=[TaskBreakdown(task_number=1, max_points=1, earned_points=1, status="Correct")],
    )


def make_payload_dict(student="s1"):
    return {
        "file_bytes": "AAAA", "file_name": "w.txt", "submission_type": "standard_test",
        "subject_id": "history", "student_id": student,
    }


class TestEvaluatorDependencies:
    def _evaluator(self, **kwargs):
        from app.services.evaluator import StudentEvaluator
        from app.jobs import JobStore

        deps = dict(pipeline=None, store=None, key_store=None)
        deps.update(kwargs)
        return StudentEvaluator(**deps)

    def test_requires_pipeline_and_store(self):
        with pytest.raises(TypeError):
            self._evaluator(pipeline=object(), store=None)
        with pytest.raises(TypeError):
            self._evaluator(pipeline=None, store=object())

    def test_rejects_non_callable_run(self):
        with pytest.raises(TypeError, match="методом run"):
            self._evaluator(pipeline=object(), store=object())


class TestDelegation:
    def _evaluator(self, run_impl, tmp_path):
        from app.jobs import JobStore
        from app.services.evaluator import StudentEvaluator

        class FakePipeline:
            def __init__(self):
                self.calls = []

            def run(self, payload, file_bytes, file_name, job_id=None):
                self.calls.append((payload, file_bytes, file_name, job_id))
                return run_impl(payload)

        pipeline = FakePipeline()
        evaluator = StudentEvaluator(
            pipeline=pipeline, store=JobStore(str(tmp_path / "jobs.db")),
        )
        return evaluator, pipeline

    def test_exact_arguments_relayed_once(self, tmp_path):
        calls = []

        def run_impl(payload):
            calls.append(payload.student_id)
            return make_assessment()

        evaluator, pipeline = self._evaluator(run_impl, tmp_path)
        result = evaluator.evaluate(make_payload_dict(), b"bytes", "w.txt", job_id="j1")
        assert isinstance(result, AssessmentResult)
        assert len(pipeline.calls) == 1
        payload, file_bytes, file_name, job_id = pipeline.calls[0]
        assert (payload.student_id, file_bytes, file_name, job_id) == ("s1", b"bytes", "w.txt", "j1")
        assert calls == ["s1"]

    def test_rag_stub_is_serializable(self, tmp_path):
        def run_impl(payload):
            out = make_assessment()
            broken = out.task_breakdown[0]
            broken.recommended_topics = "RAG недоступен (Qdrant localhost:6333)"
            return out

        evaluator, _ = self._evaluator(run_impl, tmp_path)
        saved = evaluator.evaluate(make_payload_dict(), b"x", "w.txt", job_id="j-rag")
        assert saved.task_breakdown[0].recommended_topics.startswith("RAG недоступен")

    def test_save_uses_store_api(self, tmp_path, monkeypatch):
        from app.jobs import JobStore
        from app.services import evaluator as evaluator_module
        from app.services.evaluator import StudentEvaluator

        saved = {}

        class FakePipeline:
            def run(self, payload, file_bytes, file_name, job_id=None):
                return make_assessment(total=2.0, maximum=2.0)

        class FakeStore(JobStore):
            def save_result(self, record):
                assert isinstance(record, EvaluationRecord)
                saved["record"] = record

        evaluator = StudentEvaluator(pipeline=FakePipeline(), store=FakeStore(str(tmp_path / "x.db")))
        evaluator.evaluate(make_payload_dict(), b"x", "w.txt", job_id="j-store", test_name="Вариант 7")
        assert saved["record"].test_title == "Вариант 7"
        assert saved["record"].job_id == "j-store"

    def test_failure_bubbles_without_save(self, tmp_path):
        from app.jobs import JobStore
        from app.services.evaluator import StudentEvaluator

        class BadPipeline:
            def run(self, payload, file_bytes, file_name, job_id=None):
                raise RuntimeError("пайплайн упал")

        class FailOnSaveStore(JobStore):
            def save_result(self, record):  # pragma: no cover - не должен вызываться
                raise AssertionError("save_result must not be called on failure")

        evaluator = StudentEvaluator(pipeline=BadPipeline(), store=FailOnSaveStore(str(tmp_path / "x.db")))
        with pytest.raises(RuntimeError, match="пайплайн упал"):
            evaluator.evaluate(make_payload_dict(), b"x", "w.txt", job_id="j-fail")
