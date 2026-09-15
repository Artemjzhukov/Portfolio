"""Тесты Pydantic-схем: валидные и невалидные payload'ы."""

import base64

import pytest
from pydantic import ValidationError

from app.schemas import (
    AssessmentResult,
    CriterionEvaluation,
    EGEEvaluation,
    ExtractedSubmission,
    OCRSegment,
    RubricCriterion,
    SubmissionInput,
    TaskBreakdown,
    TaskRubric,
    derive_status,
    validate_evaluation,
)


def make_input(**kwargs):
    base = dict(
        file_bytes=base64.b64encode(b"hello").decode(),
        submission_type="standard_test",
        subject_id="history",
        student_id="chat-42",
        answer_key={"1": "3"},
    )
    base.update(kwargs)
    return base


class TestSubmissionInput:
    def test_valid_input(self):
        obj = SubmissionInput(**make_input())
        assert obj.subject_id == "history"

    def test_both_file_sources_rejected(self):
        with pytest.raises(ValidationError, match="ровно один источник"):
            SubmissionInput(**make_input(file_url="http://x"))

    def test_no_file_source_rejected(self):
        with pytest.raises(ValidationError):
            SubmissionInput(**make_input(file_bytes=None))

    def test_invalid_base64_rejected(self):
        with pytest.raises(ValidationError, match="base64"):
            SubmissionInput(**make_input(file_bytes="!!!not-base64!!!"))

    def test_standard_test_requires_answer_key(self):
        with pytest.raises(ValidationError, match="answer_key"):
            SubmissionInput(**make_input(answer_key=None))

    def test_bad_subject_id_rejected(self):
        with pytest.raises(ValidationError):
            SubmissionInput(**make_input(subject_id="History-2025!"))


class TestExtractedSubmission:
    def test_duplicate_task_numbers_rejected(self):
        with pytest.raises(ValidationError, match="дубликаты"):
            ExtractedSubmission(
                source_type="docx",
                segments=[OCRSegment(task_number=5, text="a"), OCRSegment(task_number=5, text="b")],
            )

    def test_blank_segment_text_rejected(self):
        with pytest.raises(ValidationError):
            OCRSegment(task_number=1, text="   ")

    def test_unmatched_allowed(self):
        obj = ExtractedSubmission(
            source_type="image_ocr",
            segments=[OCRSegment(task_number=1, text="ответ")],
            unmatched_segments=[OCRSegment(task_number=None, text="шапка")],
        )
        assert obj.unmatched_segments[0].task_number is None


class TestRubrics:
    def test_valid_rubric(self, rubric_task19):
        assert rubric_task19.max_points == 3
        assert rubric_task19.criteria[0].criterion_id == "K1"

    def test_ladder_must_reach_max(self):
        with pytest.raises(ValidationError, match="max_points"):
            RubricCriterion(
                criterion_id="K1", title_ru="t", description_ru="d", max_points=2,
                deduction_ladder=[{"points": 0, "condition_ru": "нет"}, {"points": 1, "condition_ru": "часть"}],
            )

    def test_ladder_must_have_zero(self):
        with pytest.raises(ValidationError, match="points == 0"):
            RubricCriterion(
                criterion_id="K1", title_ru="t", description_ru="d", max_points=2,
                deduction_ladder=[{"points": 1, "condition_ru": "часть"}, {"points": 2, "condition_ru": "всё"}],
            )

    def test_duplicate_ladder_steps_rejected(self):
        with pytest.raises(ValidationError, match="K1"):
            RubricCriterion(
                criterion_id="K1", title_ru="t", description_ru="d", max_points=2,
                deduction_ladder=[{"points": 0, "condition_ru": "нет"}, {"points": 0, "condition_ru": "нет2"}],
            )

    def test_criteria_sum_must_equal_max(self, rubric_task19):
        data = rubric_task19.model_dump()
        data["max_points"] = 10  # сумма критериев = 3
        with pytest.raises(ValidationError, match="sum"):
            TaskRubric(**data)

    def test_bad_criterion_id_pattern(self):
        with pytest.raises(ValidationError):
            RubricCriterion(
                criterion_id="A1", title_ru="t", description_ru="d", max_points=1,
                deduction_ladder=[{"points": 0, "condition_ru": "нет"}, {"points": 1, "condition_ru": "да"}],
            )


class TestEvaluation:
    def test_full_deduction_requires_reason(self):
        crit = RubricCriterion(
            criterion_id="K1", title_ru="t", description_ru="d", max_points=1,
            deduction_ladder=[{"points": 0, "condition_ru": "нет"}, {"points": 1, "condition_ru": "да"}],
        )
        with pytest.raises(ValueError, match="обоснования"):
            validate_evaluation(
                CriterionEvaluation(criterion_id="K1", earned_points=0, quote_from_answer="цитата"), crit
            )

    def test_deduction_requires_quote(self):
        crit = RubricCriterion(
            criterion_id="K1", title_ru="t", description_ru="d", max_points=1,
            deduction_ladder=[{"points": 0, "condition_ru": "нет"}, {"points": 1, "condition_ru": "да"}],
        )
        with pytest.raises(ValueError, match="цитаты"):
            validate_evaluation(
                CriterionEvaluation(criterion_id="K1", earned_points=0, deduction_reason_ru="не то"), crit
            )

    def test_out_of_ladder_points_rejected(self):
        crit = RubricCriterion(
            criterion_id="K1", title_ru="t", description_ru="d", max_points=2,
            deduction_ladder=[{"points": 0, "condition_ru": "нет"}, {"points": 2, "condition_ru": "всё"}],
        )
        with pytest.raises(ValueError, match="вне ступеней"):
            validate_evaluation(
                CriterionEvaluation(criterion_id="K1", earned_points=1, quote_from_answer="q",
                                    deduction_reason_ru="r"),
                crit,
            )

    def test_no_reason_when_full_credit(self, rubric_task19):
        k1 = rubric_task19.criterion("K1")
        with pytest.raises(ValueError, match="обоснование не допускается"):
            validate_evaluation(
                CriterionEvaluation(criterion_id="K1", earned_points=2, deduction_reason_ru="всё ок"),
                k1,
            )

    def test_ege_evaluation_duplicate_criteria(self):
        with pytest.raises(ValidationError, match="дубликаты"):
            EGEEvaluation(
                task_number=19,
                criteria_evaluations=[
                    CriterionEvaluation(criterion_id="K1", earned_points=1),
                    CriterionEvaluation(criterion_id="K1", earned_points=1),
                ],
            )


class TestAssessmentResult:
    def test_percentage_recomputed(self):
        result = AssessmentResult(
            student_id="s", subject_id="history", submission_type="standard_test",
            total_score=3, max_possible_score=4, percentage=0,
            summary_feedback="тест",
            task_breakdown=[],
        )
        assert result.percentage == 75.0

    def test_zero_max_safe(self):
        result = AssessmentResult(
            student_id="s", subject_id="history", submission_type="ege_exam",
            total_score=0, max_possible_score=0, percentage=0,
            summary_feedback="",
        )
        assert result.percentage == 0.0


class TestHelpers:
    def test_derive_status(self):
        assert derive_status(3, 3) == "Correct"
        assert derive_status(1, 3) == "Partially Correct"
        assert derive_status(0, 3) == "Incorrect"

    def test_task_breakdown_requires_status(self):
        with pytest.raises(ValidationError):
            TaskBreakdown(task_number=1, max_points=1, earned_points=0)

