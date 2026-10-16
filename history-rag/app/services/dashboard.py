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
    MaterialLink,
    StudentDashboard,
    TaskBreakdown,
    TopicMastery,
)
from app.services.topic_materials import resolve_materials

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


def _roadmap_from_rows(
    rows: list[dict],
    *,
    materials_store=None,
    media_dir=None,
    subject_id: str | None = None,
) -> list[DashboardTopicItem]:
    """Темы из recommended_topics проваленных заданий, порядок стабильный.

    Материалы прикрепляются к строке темы: сначала файл учителя, затем
    авто-медиа. Без стора/предмета — пустой список материалов.
    """
    seen: list[str] = []
    for row in rows:
        for raw in row.get("task_breakdown") or []:
            task = TaskBreakdown(**raw)
            if task.status == "Correct":
                continue
            topic = (task.recommended_topics or "").strip()
            if topic and topic not in seen:
                seen.append(topic)
    items: list[DashboardTopicItem] = []
    for topic in seen:
        materials: list[MaterialLink] = []
        if materials_store is not None and subject_id is not None:
            materials = resolve_materials(materials_store, media_dir, subject_id, topic)
        items.append(
            DashboardTopicItem(
                topic_ru=topic, status=TopicMastery.NEEDS_REVIEW,
                source=ROADMAP_SOURCE, materials=materials,
            )
        )
    return items


def build_student_dashboard(
    store,
    student_id: str,
    *,
    limit: int = DEFAULT_LIMIT,
    subject_id: str | None = None,
    materials_store=None,
    media_dir=None,
) -> StudentDashboard:
    """Собирает StudentDashboard ученика из results.

    Args:
        store: JobStore (или мок с list_recent/count_results).
        limit: сколько последних работ показать (накопительный счётчик — всегда по всем).
        subject_id: опциональный фильтр предмета.
        materials_store: TopicMaterialsStore или None — без него у тем пустой список материалов.
        media_dir: каталог data/media или None.
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
    roadmap = _roadmap_from_rows(
        rows, materials_store=materials_store, media_dir=media_dir,
        subject_id=rows[0].get("subject_id") if rows else subject_id,
    )

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
