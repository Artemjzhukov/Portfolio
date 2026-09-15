"""Оркестрация пайплайна: извлечение -> проверка -> RAG -> AssessmentResult."""

from __future__ import annotations

import logging

from app.schemas import (
    AssessmentResult,
    ExtractedSubmission,
    SubmissionInput,
    TaskBreakdown,
    derive_status,
)
from app.services.checker_ege import EGEEvaluator
from app.services.checker_test import answers_match, check_standard_test
from app.services.ocr import ExtractionService
from app.services.rag import TheoryRetriever

logger = logging.getLogger(__name__)


def _breakdown_from_ege(
    rubric, evaluation, student_answer: str, retriever: TheoryRetriever, subject_id: str
) -> TaskBreakdown:
    earned = evaluation.earned(rubric)
    by_id = {e.criterion_id: e for e in evaluation.criteria_evaluations}
    criteria_text = "; ".join(
        f"{crit.criterion_id} ({by_id[crit.criterion_id].earned_points}/{crit.max_points}): "
        f"{by_id[crit.criterion_id].deduction_reason_ru or 'зачёт'}"
        for crit in rubric.criteria
        if crit.criterion_id in by_id
    )
    deduction = " ".join(
        e.deduction_reason_ru for e in evaluation.criteria_evaluations if e.deduction_reason_ru
    )
    query = " ".join(
        f"{crit.title_ru} {crit.factcheck_topics}"
        for crit in rubric.criteria
        if crit.criterion_id in by_id
        and crit.max_points - by_id[crit.criterion_id].earned_points > 0
    )
    rec = retriever.recommend(subject_id, rubric.task_number, query) if query.strip() else None
    return TaskBreakdown(
        task_number=rubric.task_number,
        max_points=rubric.max_points,
        earned_points=earned,
        status=derive_status(earned, rubric.max_points),
        student_answer=student_answer,
        correct_answer_or_criteria=criteria_text or f"критерии на {rubric.max_points} балла",
        deduction_reason=deduction,
        recommended_topics=rec.recommended_topics if rec else "",
        needs_human_review=evaluation.needs_human_review,
    )


def html_escape(text: str) -> str:
    """Экранирование для Telegram HTML-режима: произвольный текст ученика безопасен."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


TG_SHORT_LIMIT = 3500  # запас до лимита Telegram 4096


def build_telegram_short(result_data: dict) -> str:
    """Короткое HTML-сообщение для Telegram: балл + топ-3 проблемных задания.

    Длинные ответы и подробности НЕ включаются — полный отчёт уходит файлом
    (summary_feedback) и в Notion. Это устраняет класс ошибок «сообщение не
    отправилось из-за 4096 знаков / сломанного Markdown».
    """
    type_ru = "ЕГЭ" if result_data["submission_type"] == "ege_exam" else "стандартный тест"
    lines = [
        f"<b>Проверка работы — {html_escape(result_data['subject_id'])}</b>",
        f"Тип: {type_ru}",
        f"<b>Набрано: {result_data['total_score']:g} из "
        f"{result_data['max_possible_score']:g} ({result_data['percentage']:g}%)</b>",
    ]

    rank = {"Incorrect": 0, "Not Submitted": 1, "Partially Correct": 2, "Correct": 3}
    problems = sorted(result_data["task_breakdown"], key=lambda t: rank[t["status"]])
    problems = [t for t in problems if t["status"] != "Correct"][:3]

    emoji = {"Correct": "✅", "Partially Correct": "🟡", "Incorrect": "❌", "Not Submitted": "⚪"}
    for t in problems:
        reason = t["deduction_reason"]
        reason = html_escape(" ".join(reason.split())[:140]) + ("…" if len(reason) > 140 else "")
        lines.append(f"{emoji[t['status']]} №{t['task_number']}: {t['earned_points']:g}/{t['max_points']:g}")
        if reason:
            lines.append(f"   {reason}")

    if result_data.get("needs_human_review"):
        lines.append("\n⚠️ Часть оценок требует проверки преподавателем.")
    if len(problems) < len([t for t in result_data["task_breakdown"] if t["status"] != "Correct"]):
        lines.append("\n… и другие — полный разбор в файле и в Notion.")
    else:
        lines.append("\nПолный разбор — в файле и в Notion.")

    text = "\n".join(lines)
    if len(text) > TG_SHORT_LIMIT:  # теоретически возможен при огромных reason
        text = text[: TG_SHORT_LIMIT - 1] + "…"
    return text


def build_summary(result_data: dict, extracted: ExtractedSubmission | None) -> str:
    """Markdown-обзор на русском для Telegram/Notion."""
    lines = [
        "## Итог проверки работы",
        f"- Предмет: {result_data['subject_id']}",
        f"- Тип работы: {'ЕГЭ' if result_data['submission_type'] == 'ege_exam' else 'стандартный тест'}",
        f"- **Набрано: {result_data['total_score']:g} из "
        f"{result_data['max_possible_score']:g} ({result_data['percentage']:g}%)**",
        "",
        "### Разбор по заданиям",
    ]
    emoji = {"Correct": "✅", "Partially Correct": "🟡", "Incorrect": "❌", "Not Submitted": "⚪"}
    for t in result_data["task_breakdown"]:
        lines.append(f"{emoji[t['status']]} №{t['task_number']}: {t['earned_points']:g}/{t['max_points']:g}")
        if t["deduction_reason"]:
            lines.append(f"   · {t['deduction_reason']}")
        if t["recommended_topics"]:
            lines.append(f"   · {t['recommended_topics'].replace(chr(10), chr(10) + '   ')}")
    if extracted is not None and extracted.unmatched_segments:
        lines += ["", "⚠️ В работе есть фрагменты, которые не удалось привязать к номеру задачи — проверьте вручную."]
    if result_data.get("needs_human_review"):
        lines += ["", "⚠️ Часть оценок помечена для проверки преподавателем."]
    if result_data.get("warnings"):
        lines += ["", *(f"⚠️ {w}" for w in result_data["warnings"])]
    return "\n".join(lines)


class AssessmentPipeline:
    """Инъекция зависимостей для тестируемости (подмена в тестах через конструктор)."""

    def __init__(
        self,
        extraction: ExtractionService,
        ege_evaluator: EGEEvaluator,
        retriever: TheoryRetriever,
    ) -> None:
        self.extraction = extraction
        self.ege = ege_evaluator
        self.retriever = retriever

    def run(
        self,
        payload: SubmissionInput,
        file_bytes: bytes,
        file_name: str | None,
        job_id: str | None = None,
    ) -> AssessmentResult:
        """job_id пробрасывается только для логов (корреляция джоба <-> этапы)."""
        extracted = self.extraction.extract(file_bytes=file_bytes, file_name=file_name)
        warnings: list[str] = []
        ctx = f"job={job_id or '-'}"

        logger.info(
            "%s extracted: source=%s pages=%s segments=%d unmatched=%d",
            ctx, extracted.source_type, extracted.pages, len(extracted.segments),
            len(extracted.unmatched_segments),
        )

        if extracted.unmatched_segments:
            warnings.append(
                f"Не удалось привязать к номерам задач {len(extracted.unmatched_segments)} фрагмент(ов)."
            )

        if payload.submission_type == "standard_test":
            breakdowns, unkeyed = check_standard_test(extracted, payload.answer_key or {})
            if unkeyed:
                warnings.append(
                    f"Задания {unkeyed} есть в работе, но отсутствуют в answer_key — не учтены."
                )
        else:
            breakdowns = self._run_ege(payload, extracted, warnings)

        total = sum(b.earned_points for b in breakdowns)
        max_possible = sum(b.max_points for b in breakdowns)
        needs_review = any(b.needs_human_review for b in breakdowns)
        percentage = round(total / max_possible * 100, 1) if max_possible > 0 else 0.0

        result_data = {
            "student_id": payload.student_id,
            "subject_id": payload.subject_id,
            "submission_type": payload.submission_type,
            "total_score": float(total),
            "max_possible_score": float(max_possible),
            "percentage": percentage,
            "summary_feedback": "",
            "task_breakdown": [b.model_dump() for b in breakdowns],
            "needs_human_review": needs_review,
            "warnings": warnings,
        }
        result_data["summary_feedback"] = build_summary(result_data, extracted)
        result_data["telegram_short"] = build_telegram_short(result_data)
        logger.info(
            "%s assessed: total=%g/%g review=%s warnings=%d",
            ctx, float(total), float(max_possible), needs_review, len(warnings),
        )
        return AssessmentResult.model_validate(result_data)

    def _run_ege(
        self, payload: SubmissionInput, extracted: ExtractedSubmission, warnings: list[str]
    ) -> list[TaskBreakdown]:
        rubrics = self.ege.load_rubrics(payload.subject_id)
        if not rubrics:
            warnings.append(
                f"Для предмета '{payload.subject_id}' не найдено ни одной рубрики в "
                f"{self.ege.s.criteria_dir}/{payload.subject_id} — задания не оценивались."
            )
        answer_key = payload.answer_key or {}
        segments = {s.task_number: s for s in extracted.segments if s.task_number is not None}
        numeric = set(segments) | set(rubrics) | {int(k) for k in answer_key if str(k).strip().isdigit()}
        all_numbers = sorted(numeric) + [k for k in answer_key if not str(k).strip().isdigit()]

        breakdowns: list[TaskBreakdown] = []
        for num in all_numbers:
            seg = segments.get(num)
            student_answer = seg.text if seg else ""

            if num in rubrics:
                rubric = rubrics[num]
                evaluation = self.ege.evaluate_task(rubric, student_answer)
                breakdowns.append(
                    _breakdown_from_ege(
                        rubric, evaluation, student_answer, self.retriever, payload.subject_id
                    )
                )
                continue

            # Задание без рубрики: если есть ключ — детерминированная проверка,
            # иначе — ручная проверка (нулевой балл + флаг).
            correct = answer_key.get(str(num))
            if correct is not None:
                ok = answers_match(student_answer, correct)
                breakdowns.append(
                    TaskBreakdown(
                        task_number=num, max_points=1, earned_points=1 if ok else 0,
                        status=derive_status(1 if ok else 0, 1),
                        student_answer=student_answer,
                        correct_answer_or_criteria=correct,
                        deduction_reason="" if ok else f"Правильный ответ: {correct}. В работе: {student_answer}",
                    )
                )
            else:
                breakdowns.append(
                    TaskBreakdown(
                        task_number=num, max_points=1, earned_points=0, status="Not Submitted",
                        student_answer=student_answer,
                        correct_answer_or_criteria="",
                        deduction_reason="Нет ни ключа, ни рубрики для этого задания",
                        needs_human_review=True,
                    )
                )
        return breakdowns
