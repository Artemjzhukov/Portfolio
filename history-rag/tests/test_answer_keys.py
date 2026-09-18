"""Тесты хранилища эталонных ответов и приоритетов payload > файл."""

import pytest

from app.services.answer_keys import AnswerKeyStore, resolve_answer_key
from app.services.pipeline import AssessmentPipeline
from app.schemas import AnswerKeyFile, ExtractedSubmission, OCRSegment, SubmissionInput

from tests.conftest import FakeLLM

VALID = '{"schema_version": 1, "subject_id": "history", "answers": {"1": "3", "2": "5"}}'


@pytest.fixture
def store(settings, tmp_path):
    settings.answer_keys_dir = tmp_path
    return AnswerKeyStore(settings)


class TestAnswerKeyStore:
    def test_loads_file(self, store, tmp_path):
        (tmp_path / "history.json").write_text(VALID, encoding="utf-8")
        assert store.get("history") == {"1": "3", "2": "5"}

    def test_missing_subject_empty(self, store):
        assert store.get("math") == {}

    def test_wrong_subject_id_rejected(self, store, tmp_path):
        (tmp_path / "history.json").write_text(
            '{"schema_version": 1, "subject_id": "social_studies", "answers": {"1": "3"}}',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="history"):
            store.get("history")


class TestResolve:
    def _payload(self, answer_key=None):
        return SubmissionInput(
            file_bytes="AAAA", file_name="w.txt", submission_type="standard_test",
            subject_id="history", student_id="s1", answer_key=answer_key,
        )

    def test_payload_wins_over_file(self, store, tmp_path):
        (tmp_path / "history.json").write_text(VALID, encoding="utf-8")
        assert resolve_answer_key(self._payload({"1": "9"}), store) == {"1": "9"}

    def test_file_used_when_payload_empty(self, store, tmp_path):
        (tmp_path / "history.json").write_text(VALID, encoding="utf-8")
        assert resolve_answer_key(self._payload(None), store) == {"1": "3", "2": "5"}

    def test_none_anywhere(self, store):
        assert resolve_answer_key(self._payload(None), store) == {}

    def test_answer_key_file_schema(self):
        obj = AnswerKeyFile.model_validate_json(VALID)
        assert obj.answers["2"] == "5"


class TestPipelineWithStore:
    def _extracted(self):
        return ExtractedSubmission(
            source_type="plain_text",
            segments=[OCRSegment(task_number=1, text="3")],
        )

    def test_standard_test_graded_from_store(self, settings, tmp_path):
        """answer_key отсутствует в payload — ключи берутся из хранилища."""
        settings.answer_keys_dir = tmp_path
        (tmp_path / "history.json").write_text(VALID, encoding="utf-8")
        pipeline = AssessmentPipeline(
            extraction=None, ege_evaluator=None, retriever=None,
            key_store=AnswerKeyStore(settings),
        )

        class FixedExtraction:
            def extract(self, *, file_bytes, file_name):
                return self._extracted()

            _extracted = TestPipelineWithStore._extracted

        pipeline.extraction = FixedExtraction()
        payload = SubmissionInput(
            file_bytes="AAAA", file_name="w.txt", submission_type="standard_test",
            subject_id="history", student_id="s1",
        )
        result = pipeline.run(payload, b"x", "w.txt")
        assert result.total_score == 1.0
        assert result.task_breakdown[0].status == "Correct"
        assert not result.needs_human_review

    def test_standard_test_without_any_key_flags_review(self, settings, tmp_path):
        settings.answer_keys_dir = tmp_path  # пустой каталог — эталонов нет нигде
        pipeline = AssessmentPipeline(
            extraction=None, ege_evaluator=None, retriever=None,
            key_store=AnswerKeyStore(settings),
        )

        class FixedExtraction(TestPipelineWithStore):
            def extract(self, *, file_bytes, file_name):
                return TestPipelineWithStore._extracted(self)

        pipeline.extraction = FixedExtraction()
        payload = SubmissionInput(
            file_bytes="AAAA", file_name="w.txt", submission_type="standard_test",
            subject_id="history", student_id="s1",
        )
        result = pipeline.run(payload, b"x", "w.txt")
        assert result.needs_human_review
        assert any("Эталонные ответы не найдены" in w for w in result.warnings)
