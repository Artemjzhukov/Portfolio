"""Сборка дашборда ученика из JobStore (таблица results).

Никаких вызовов LLM/Qdrant: читаем только сохранённые EvaluationRecord.
Источники для тестов подменяются через конструктор (duck-typing стора).
"""

from __future__ import annotations

import logging

from app.schemas import (
    DashboardTaskItem,
    DashboardTestItem,
    DashboardTopicItem,
    StudentDashboard,
    TaskBreakdown,
    TopicMastery,
)

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 10
ROADMAP_SOURCE = "RAG"


def _to_task_items(raw_tasks: list[dict]) -> list[DashboardTaskItem]:
    """Маппинг сохранённого breakdown -> DashboardTaskItem (единственная точка)."""
    items: list[DashboardTaskItem] = []
    for raw in raw_tasks:
        task = TaskBreakdown(**raw)
        items.append(
            DashboardTaskItem(
                task_number=task.task_number,
                earned_points=task.earned_points,
                max_points=task.max_points,
                status=task.status,
                deduction_reason_ru=task.deduction_reason,
                topics_to_review_ru=task.recommended_topics,
            )
        )
    return items


def _roadmap_from_rows(rows: list[dict]) -> list[DashboardTopicItem]:
    """Темы из recommended_topics проваленных заданий, порядок стабильный."""
    seen: list[str] = []
    for row in rows:
        for raw in row.get("task_breakdown") or []:
            task = TaskBreakdown(**raw)
            if task.status == "Correct":
                continue
            topic = (task.recommended_topics or "").strip()
            if topic and topic not in seen:
                seen.append(topic)
    return [
        DashboardTopicItem(topic_ru=topic, status=TopicMastery.NEEDS_REVIEW, source=ROADMAP_SOURCE)
        for topic in seen
    ]


def build_student_dashboard(store, student_id: str, *, limit: int = DEFAULT_LIMIT, subject_id: str | None = None) -> StudentDashboard:
    """Собирает StudentDashboard ученика из results.

    Args:
        store: JobStore (или мок с list_recent/count_results).
        limit: сколько последних работ показать (накопительный счётчик — всегда по всем).
        subject_id: опциональный фильтр предмета.
    """
    rows = [r for r in store.list_recent(student_id, limit=limit) if subject_id is None or r.get("subject_id") == subject_id]
    total_tests = store.count_results(student_id) if subject_id is None else len(
        [r for r in store.list_recent(student_id, limit=10**9) if r.get("subject_id") == subject_id]
    )

    recent_tests = [
        DashboardTestItem(
            job_id=r["job_id"],
            test_title=r["test_title"],
            submission_type=r["submission_type"],
            total_score=r["total_score"],
            max_possible_score=r["max_possible_score"],
            percentage=r["percentage"],
            evaluated_at=r["evaluated_at"],
            needs_human_review=bool(r.get("needs_human_review", False)),
        )
        for r in rows
    ]
    tasks = _to_task_items(rows[0]["task_breakdown"]) if rows else []
    roadmap = _roadmap_from_rows(rows)

    overall_score = round(sum(r["total_score"] for r in rows), 2)
    earned_total = sum(r["total_score"] for r in rows)
    max_total = sum(r["max_possible_score"] for r in rows)
    pass_rate = round(earned_total / max_total * 100, 1) if max_total > 0 else 0.0

    logger.info("dashboard built: student=%s tests=%d total=%d", student_id, len(rows), total_tests)
    return StudentDashboard(
        student_id=student_id,
        overall_score=overall_score,
        pass_rate=pass_rate,
        covered_topics_count=len(roadmap),
        total_tests_count=total_tests,
        recent_tests=recent_tests,
        tasks=tasks,
        roadmap=roadmap,
        materials=[],
    )
