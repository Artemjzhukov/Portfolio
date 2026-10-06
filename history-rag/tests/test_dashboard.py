"""Тесты сборки дашборда: сервис build_student_dashboard на моках стора."""

import pytest

from app.schemas import TaskBreakdown


def rec(job, total=3.0, maximum=4.0, evaluated_at=100.0, student="s1", tasks=None, review=False):
    return {
        "job_id": job,
        "student_id": student,
        "subject_id": "history",
        "submission_type": "standard_test",
        "test_name": None,
        "test_title": f"T {job}",
        "total_score": total,
        "max_possible_score": maximum,
        "percentage": round(total / maximum * 100, 1) if maximum > 0 else 0.0,
        "task_breakdown": tasks if tasks is not None else [
            {"task_number": 1, "max_points": 1, "earned_points": 1, "status": "Correct",
             "student_answer": "3", "correct_answer_or_criteria": "3",
             "deduction_reason": "", "recommended_topics": "", "needs_human_review": False},
        ],
        "needs_human_review": review,
        "evaluated_at": evaluated_at,
    }


def failed_task(number, reason, topics):
    return {
        "task_number": number, "max_points": 1, "earned_points": 0, "status": "Incorrect",
        "student_answer": "x", "correct_answer_or_criteria": "y",
        "deduction_reason": reason, "recommended_topics": topics, "needs_human_review": False,
    }


class FakeStore:
    def __init__(self, rows):
        self._rows = rows

    def list_recent(self, student_id, limit=10):
        return [r for r in self._rows if r["student_id"] == student_id][:limit]

    def count_results(self, student_id):
        return sum(1 for r in self._rows if r["student_id"] == student_id)

    def get_result_record(self, job_id):
        for r in self._rows:
            if r["job_id"] == job_id:
                return r
        return None


class TestBuildDashboard:
    def test_full_payload(self):
        from app.services.dashboard import build_student_dashboard

        store = FakeStore([
            rec("j1", total=3, maximum=4, evaluated_at=101.0,
                tasks=[failed_task(1, "Перепутал дату", "Отмена крепостного права")]),
            rec("j2", total=4, maximum=4, evaluated_at=102.0),
        ])
        dash = build_student_dashboard(store, "s1")
        assert dash.student_id == "s1"
        assert dash.total_tests_count == 2
        assert dash.overall_score == 7.0
        assert dash.pass_rate == 87.5
        assert [t.job_id for t in dash.recent_tests] == ["j1", "j2"]
        assert dash.recent_tests[0].test_title == "T j1"
        # детали — из первой работы в выдаче
        assert dash.tasks[0].deduction_reason_ru == "Перепутал дату"
        assert dash.tasks[0].topics_to_review_ru == "Отмена крепостного права"
        assert dash.covered_topics_count == 1
        assert dash.roadmap[0].topic_ru == "Отмена крепостного права"
        assert dash.roadmap[0].status.value == "needs_review"

    def test_subject_filter(self):
        from app.services.dashboard import build_student_dashboard

        rows = [rec("j1", evaluated_at=101.0)]
        rows[0]["subject_id"] = "math"
        rows.append(rec("j2", evaluated_at=102.0))
        dash = build_student_dashboard(FakeStore(rows), "s1", subject_id="history")
        assert dash.total_tests_count == 1
        assert [t.job_id for t in dash.recent_tests] == ["j2"]

    def test_own_student_only(self):
        from app.services.dashboard import build_student_dashboard

        dash = build_student_dashboard(FakeStore([rec("j1", student="other")]), "s1")
        assert dash.total_tests_count == 0
        assert dash.recent_tests == []
        assert dash.pass_rate == 0.0
        assert dash.overall_score == 0.0

    def test_limit_is_default_ten(self):
        from app.services.dashboard import build_student_dashboard

        rows = [rec(f"j{i}", evaluated_at=100.0 + i) for i in range(12)]
        dash = build_student_dashboard(FakeStore(rows), "s1")
        assert len(dash.recent_tests) == 10
        assert dash.total_tests_count == 12

    def test_respects_custom_limit(self):
        from app.services.dashboard import build_student_dashboard

        rows = [rec(f"j{i}", evaluated_at=100.0 + i) for i in range(3)]
        dash = build_student_dashboard(FakeStore(rows), "s1", limit=2)
        assert len(dash.recent_tests) == 2
        assert dash.total_tests_count == 3  # накопительный счётчик — по всем работам

    def test_correct_tasks_not_in_roadmap(self):
        from app.services.dashboard import build_student_dashboard

        dash = build_student_dashboard(FakeStore([rec("j1")]), "s1")
        assert dash.roadmap == []
        assert dash.covered_topics_count == 0

    def test_zero_max_is_safe(self):
        from app.services.dashboard import build_student_dashboard

        dash = build_student_dashboard(FakeStore([rec("j1", total=0, maximum=0)]), "s1")
        assert dash.pass_rate == 0.0
        assert dash.overall_score == 0.0

    def test_multi_topic_roadmap_order_stable(self):
        from app.services.dashboard import build_student_dashboard

        dash = build_student_dashboard(FakeStore([rec(
            "j1", tasks=[
                failed_task(1, "r1", "Тема Б"),
                failed_task(2, "r2", "Тема А"),
            ],
        )]), "s1")
        assert [t.topic_ru for t in dash.roadmap] == ["Тема Б", "Тема А"]
        assert all(t.source == "RAG" for t in dash.roadmap)

    def test_mapping_reuses_single_point(self):
        raw = {
            "task_number": 5, "max_points": 2, "earned_points": 1, "status": "Partially Correct",
            "student_answer": "a", "correct_answer_or_criteria": "b",
            "deduction_reason": "c", "recommended_topics": "t", "needs_human_review": False,
        }
        item = TaskBreakdown(**raw)
        assert item.earned_points == 1

    def test_empty_recommended_topics_skipped_in_roadmap(self):
        from app.services.dashboard import build_student_dashboard

        dash = build_student_dashboard(FakeStore([rec(
            "j1", tasks=[failed_task(1, "r", "")],
        )]), "s1")
        assert dash.roadmap == []

