"""Тесты схем дашборда, Notion-синка и Telegram (фаза: прогресс и оценка)."""

import pytest
from pydantic import ValidationError

from app.schemas import (
    AssessmentResult,
    DashboardAccessQuery,
    DashboardTaskItem,
    DashboardTestItem,
    DashboardTopicItem,
    EvaluationRecord,
    MaterialLink,
    NotionSyncPayload,
    StudentDashboard,
    SubmissionInput,
    TaskBreakdown,
    TelegramResultMessage,
    TopicMastery,
    build_test_title,
    DashboardTokenIssue,
    DashboardTokenRecord,
)


def make_result(**kwargs):
    base = dict(
        student_id="s1",
        subject_id="history",
        submission_type="standard_test",
        total_score=3,
        max_possible_score=4,
        percentage=0,
        summary_feedback="s",
        task_breakdown=[
            TaskBreakdown(task_number=1, max_points=1, earned_points=1, status="Correct"),
        ],
    )
    base.update(kwargs)
    return AssessmentResult(**base)


class TestSubmissionTestName:
    def _base(self, **kwargs):
        import base64
        base = dict(
            file_bytes=base64.b64encode(b"hello").decode(),
            submission_type="standard_test",
            subject_id="history",
            student_id="s1",
        )
        base.update(kwargs)
        return base

    def test_accepts_test_name(self):
        obj = SubmissionInput(**self._base(test_name="Вариант 3"))
        assert obj.test_name == "Вариант 3"

    def test_test_name_defaults_none(self):
        assert SubmissionInput(**self._base()).test_name is None

    def test_empty_test_name_rejected(self):
        with pytest.raises(ValidationError):
            SubmissionInput(**self._base(test_name=""))

    def test_too_long_test_name_rejected(self):
        with pytest.raises(ValidationError):
            SubmissionInput(**self._base(test_name="x" * 201))


class TestBuildTestTitle:
    def test_explicit_name_wins(self):
        assert build_test_title("history", 0.0, "  Вариант 3 ") == "Вариант 3"

    def test_default_subject_and_date(self):
        assert build_test_title("history", 0.0) == "history · 1970-01-01"

    def test_blank_falls_back(self):
        assert build_test_title("history", 0.0, "   ") == "history · 1970-01-01"


class TestEvaluationRecord:
    def test_from_assessment_maps_fields(self):
        rec = EvaluationRecord.from_assessment("j1", make_result(), test_name="Вариант 3", evaluated_at=100.0)
        assert rec.job_id == "j1"
        assert rec.test_title == "Вариант 3"
        assert rec.percentage == 75.0
        assert rec.evaluated_at == 100.0
        assert len(rec.task_breakdown) == 1

    def test_from_assessment_default_title(self):
        rec = EvaluationRecord.from_assessment("j1", make_result(), evaluated_at=0.0)
        assert rec.test_title == "history · 1970-01-01"


class TestDashboardTaskItem:
    def test_valid_correct(self):
        item = DashboardTaskItem(task_number=1, earned_points=2, max_points=2, status="Correct")
        assert item.status == "Correct"

    def test_valid_partial(self):
        item = DashboardTaskItem(task_number=1, earned_points=1, max_points=2, status="Partially Correct")
        assert item.status == "Partially Correct"

    def test_not_submitted_allowed_with_zero(self):
        item = DashboardTaskItem(task_number=2, earned_points=0, max_points=1, status="Not Submitted")
        assert item.status == "Not Submitted"

    def test_mismatched_status_rejected(self):
        with pytest.raises(ValidationError, match="согласуется"):
            DashboardTaskItem(task_number=1, earned_points=1, max_points=2, status="Incorrect")

    def test_earned_above_max_rejected(self):
        with pytest.raises(ValidationError, match="превышать max_points"):
            DashboardTaskItem(task_number=1, earned_points=3, max_points=2, status="Correct")


class TestDashboardTestItem:
    def test_percentage_recomputed(self):
        item = DashboardTestItem(
            job_id="j1", test_title="t", submission_type="ege_exam",
            total_score=3, max_possible_score=4, percentage=0, evaluated_at=1.0,
        )
        assert item.percentage == 75.0


class TestStudentDashboard:
    def _item(self, job):
        return DashboardTestItem(
            job_id=job, test_title=job, submission_type="standard_test",
            total_score=1, max_possible_score=2, percentage=50.0, evaluated_at=1.0,
        )

    def test_valid_dashboard(self):
        dash = StudentDashboard(
            student_id="s1", overall_score=10.5, pass_rate=75.0,
            covered_topics_count=4, total_tests_count=5,
            recent_tests=[self._item("j1"), self._item("j2")],
            roadmap=[DashboardTopicItem(topic_ru="Реформы", status=TopicMastery.LEARNED)],
        )
        assert dash.total_tests_count == 5

    def test_more_than_ten_recent_rejected(self):
        with pytest.raises(ValidationError, match="at most 10"):
            StudentDashboard(
                student_id="s1", overall_score=1, pass_rate=10.0,
                covered_topics_count=0, total_tests_count=11,
                recent_tests=[self._item(f"j{i}") for i in range(11)],
            )

    def test_total_below_recent_rejected(self):
        with pytest.raises(ValidationError, match="total_tests_count"):
            StudentDashboard(
                student_id="s1", overall_score=1, pass_rate=10.0,
                covered_topics_count=0, total_tests_count=1,
                recent_tests=[self._item("j1"), self._item("j2")],
            )

    def test_bad_topic_status_rejected(self):
        with pytest.raises(ValidationError):
            DashboardTopicItem(topic_ru="x", status="unknown")


class TestMaterialLink:
    def test_media_and_external_ok(self):
        assert MaterialLink(title_ru="Карта", url="/media/history/map.png", kind="file").kind == "file"
        assert MaterialLink(title_ru="Урок", url="https://example.com/lesson.pdf", kind="pdf").kind == "pdf"

    def test_ftp_rejected(self):
        with pytest.raises(ValidationError, match="https?://"):
            MaterialLink(title_ru="x", url="ftp://example.com/f.pdf")

    def test_pdf_kind_requires_pdf_url(self):
        with pytest.raises(ValidationError, match=".pdf"):
            MaterialLink(title_ru="x", url="https://example.com/page", kind="pdf")


class TestNotionSyncPayload:
    def _base(self, **kwargs):
        base = dict(
            student_name="Иван", test_title="history · 2025-09-30",
            score=18, percentage=75.0, date="2025-09-30T10:00:00+00:00",
            dashboard_url="https://app.example/d/s1?token=abc", job_id="j1",
        )
        base.update(kwargs)
        return base

    def test_valid(self):
        assert NotionSyncPayload(**self._base()).score == 18

    def test_bad_date_rejected(self):
        with pytest.raises(ValidationError, match="ISO-8601"):
            NotionSyncPayload(**self._base(date="завтра"))

    def test_bad_url_rejected(self):
        with pytest.raises(ValidationError, match="https?://"):
            NotionSyncPayload(**self._base(dashboard_url="notaurl"))


class TestTelegramResultMessage:
    def _base(self, **kwargs):
        base = dict(
            chat_id="12345",
            text_ru="Вариант проверен! Ваш результат: 18/24 (75%).",
            dashboard_url="https://app.example/d/s1?token=abc",
        )
        base.update(kwargs)
        return base

    def test_valid_defaults_html(self):
        assert TelegramResultMessage(**self._base()).parse_mode == "HTML"

    def test_too_long_rejected(self):
        with pytest.raises(ValidationError):
            TelegramResultMessage(**self._base(text_ru="x" * 4097))

    def test_bad_parse_mode_rejected(self):
        with pytest.raises(ValidationError):
            TelegramResultMessage(**self._base(parse_mode="Markdown"))


class TestDashboardTokens:
    def test_issue_defaults_ttl(self):
        assert DashboardTokenIssue(student_id="s1", telegram_chat_id="42").ttl_hours == 72

    def test_record_valid(self):
        rec = DashboardTokenRecord(
            token_hash="a" * 64, student_id="s1", telegram_chat_id="42",
            created_at=100.0, expires_at=200.0,
        )
        assert rec.used is False

    def test_expiry_must_follow_creation(self):
        with pytest.raises(ValidationError, match="expires_at"):
            DashboardTokenRecord(
                token_hash="a" * 64, student_id="s1", telegram_chat_id="42",
                created_at=200.0, expires_at=100.0,
            )

    def test_short_token_rejected(self):
        with pytest.raises(ValidationError):
            DashboardAccessQuery(token="short")

    def test_bad_token_chars_rejected(self):
        with pytest.raises(ValidationError):
            DashboardAccessQuery(token="x" * 20 + "!!!")

