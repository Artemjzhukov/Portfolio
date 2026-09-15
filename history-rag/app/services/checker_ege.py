"""Rubric-based AI-оценщик ЕГЭ (часть 2) + загрузка рубрик из JSON.

Защита от галлюцинаций при снижении баллов:
- Structured Outputs со строгой JSON-схемой;
- дискретные ступени (deduction_ladder) вместо «придуманных» баллов;
- обязательная дословная цитата ученика для любого снижения;
- санити-чеки и валидация в Pydantic, retry, флаг needs_human_review;
- фактчек сниженных критериев через RAG-хранилище.
"""

from __future__ import annotations

import logging
import re
import statistics
from pathlib import Path

from app.config import Settings
from app.schemas import (
    CriterionEvaluation,
    EGEEvaluation,
    RubricCriterion,
    TaskRubric,
    validate_evaluation,
)
from app.services.llm import LLMClient

logger = logging.getLogger(__name__)

EVAL_SYSTEM_PROMPT = (
    "Ты — строгий и беспристрастный эксперт ЕГЭ. Оценивай ответ ученика ИСКЛЮЧИТЕЛЬНО "
    "по перечисленным критериям и их ступеням начисления баллов.\n"
    "Жёсткие правила:\n"
    "1. earned_points может быть ТОЛЬКО значением одной из ступеней критерия.\n"
    "2. Если снижаешь балл — ОБЯЗАТЕЛЬНО приведи дословную цитату из ответа ученика "
    "(quote_from_answer) и причину по-русски (deduction_reason_ru).\n"
    "3. Если не можешь процитировать место в ответе, где нарушен критерий, — НЕ СНИЖАЙ балл.\n"
    "4. Не выдумывай факты и не приписывай ученику ошибок, которых нет в его тексте. "
    "При сомнении в факте — поставь earned_points по лучшей ступени и укажи сомнение в review_reasons_ru.\n"
    "5. Ответ верни строго в JSON по схеме."
)

# Строгая JSON-схема для Structured Outputs (OpenAI strict mode):
# все поля required, additionalProperties=false.
EVALUATION_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["criteria_evaluations", "uncovered_answer_fragments", "review_reasons_ru"],
    "properties": {
        "criteria_evaluations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "criterion_id", "earned_points", "quote_from_answer", "deduction_reason_ru",
                ],
                "properties": {
                    "criterion_id": {"type": "string", "pattern": "^K\\d+$"},
                    "earned_points": {"type": "integer", "minimum": 0},
                    "quote_from_answer": {"type": "string"},
                    "deduction_reason_ru": {"type": "string"},
                },
            },
        },
        "uncovered_answer_fragments": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Части ответа ученика, не покрытые ни одним критерием.",
        },
        "review_reasons_ru": {"type": "array", "items": {"type": "string"}},
    },
}


class RubricNotFound(LookupError):
    """Рубрика для предмета/задания отсутствует в data/criteria."""


class EGEEvaluator:
    def __init__(self, llm: LLMClient, settings: Settings, factcheck=None) -> None:
        """
        Args:
            factcheck: объект с методом check(quote: str, topics: list[str]) -> str | None
                       (None = факт не подтверждён хранилищем -> ручная проверка).
        """
        self.llm = llm
        self.s = settings
        self.factcheck = factcheck

    # ------------------------------------------------------------------
    # Загрузка рубрик
    # ------------------------------------------------------------------

    def load_rubrics(self, subject_id: str) -> dict[int, TaskRubric]:
        rubric_dir = Path(self.s.criteria_dir) / subject_id
        if not rubric_dir.is_dir():
            return {}
        rubrics: dict[int, TaskRubric] = {}
        for path in sorted(rubric_dir.glob("task_*.json")):
            match = re.fullmatch(r"task_(\d+)\.json", path.name)
            if not match:
                continue
            rubric = TaskRubric.model_validate_json(path.read_text(encoding="utf-8"))
            if rubric.subject_id != subject_id:
                raise ValueError(
                    f"{path}: subject_id в файле ('{rubric.subject_id}') != папке ('{subject_id}')"
                )
            rubrics[rubric.task_number] = rubric
        return rubrics

    # ------------------------------------------------------------------
    # Промпт
    # ------------------------------------------------------------------

    def _build_user_prompt(self, rubric: TaskRubric, student_answer: str) -> str:
        lines = [
            f"Предмет: {rubric.subject_id}. Задание {rubric.task_number} "
            f"(часть {rubric.part}), максимум {rubric.max_points} балл(а).\n",
            "КРИТЕРИИ И СТУПЕНИ БАЛЛОВ:",
        ]
        for crit in rubric.criteria:
            lines.append(f"\n{crit.criterion_id} — {crit.title_ru} (максимум {crit.max_points}):")
            lines.append(f"  Описание: {crit.description_ru}")
            lines.append(crit.ladder_text())
        lines.append("\nОТВЕТ УЧЕНИКА (транскрипция, дословно):\n" + student_answer)
        lines.append("\nОцени каждый критерий (K1, K2, ...) строго по ступеням. Верни JSON по схеме.")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Оценка одного задания
    # ------------------------------------------------------------------

    def evaluate_task(self, rubric: TaskRubric, student_answer: str) -> EGEEvaluation:
        if not student_answer.strip():
            return EGEEvaluation(
                task_number=rubric.task_number,
                criteria_evaluations=[
                    CriterionEvaluation(
                        criterion_id=c.criterion_id, earned_points=0,
                        deduction_reason_ru="Ответ на задание отсутствует (пустой).",
                    )
                    for c in rubric.criteria
                ],
            )

        verdicts = self._evaluate_once(rubric, student_answer)
        problems = self._collect_problems(rubric, verdicts)

        if problems:  # одна повторная попытка с явным перечнем проблем
            verdicts = self._evaluate_once(rubric, student_answer, problems=problems)
            problems = self._collect_problems(rubric, verdicts)

        review_reasons: list[str] = list(problems)

        # Самосогласованность: спорные критерии (0 < earned < max) при votes > 1.
        if self.s.consistency_votes > 1:
            verdicts = self._reconcile_borderline(rubric, student_answer, verdicts)

        # Фактчек сниженных критериев через RAG: только ДОБАВЛЯЕТ review-флаги.
        if self.factcheck is not None:
            for ce in verdicts:
                crit = rubric.criterion(ce.criterion_id)
                deducted = crit.max_points - ce.earned_points
                if deducted > 0 and crit.factcheck_topics and ce.quote_from_answer.strip():
                    if self.factcheck.check(ce.quote_from_answer, crit.factcheck_topics) is None:
                        review_reasons.append(
                            f"Утверждение по критерию {crit.criterion_id} не подтверждено "
                            f"хранилищем материалов — требуется проверка преподавателя."
                        )

        if review_reasons:
            logger.warning(
                "task=%s needs human review: %s", rubric.task_number, "; ".join(review_reasons)
            )
        logger.info(
            "task=%s evaluated: earned=%d/%d",
            rubric.task_number, sum(v.earned_points for v in verdicts), rubric.max_points,
        )
        return EGEEvaluation(
            task_number=rubric.task_number,
            criteria_evaluations=verdicts,
            needs_human_review=bool(review_reasons),
            review_reasons_ru=review_reasons,
        )

    # ------------------------------------------------------------------

    def _evaluate_once(
        self, rubric: TaskRubric, student_answer: str, *, problems: list[str] | None = None
    ) -> list[CriterionEvaluation]:
        user_prompt = self._build_user_prompt(rubric, student_answer)
        if problems:
            user_prompt += "\n\nИСПРАВЬ ошибки предыдущей попытки:\n- " + "\n- ".join(problems)
        data = self.llm.chat(
            system=EVAL_SYSTEM_PROMPT,
            user=user_prompt,
            schema=EVALUATION_JSON_SCHEMA,
            schema_name="egee_evaluation",
        )
        by_id = {c.criterion_id: c for c in rubric.criteria}
        verdicts: list[CriterionEvaluation] = []
        for item in data.get("criteria_evaluations", []):
            try:
                ce = CriterionEvaluation.model_validate(item)
                crit = by_id.get(ce.criterion_id)
                if crit is None:
                    continue  # неизвестный критерий отбрасываем, попадёт в problems
                validate_evaluation(ce, crit)
                verdicts.append(ce)
            except (ValueError, KeyError):
                continue
        return verdicts

    def _collect_problems(
        self, rubric: TaskRubric, verdicts: list[CriterionEvaluation]
    ) -> list[str]:
        valid_ids = {c.criterion_id for c in rubric.criteria}
        seen = {ce.criterion_id for ce in verdicts}
        return [f"критерий {cid} не оценён или оценён невалидно" for cid in sorted(valid_ids - seen)]

    def _reconcile_borderline(
        self, rubric: TaskRubric, student_answer: str, verdicts: list[CriterionEvaluation]
    ) -> list[CriterionEvaluation]:
        borderline = [
            ce for ce in verdicts
            if 0 < ce.earned_points < rubric.criterion(ce.criterion_id).max_points
        ]
        if not borderline:
            return verdicts
        extra_votes = [
            self._evaluate_once(rubric, student_answer)
            for _ in range(self.s.consistency_votes - 1)
        ]
        reconciled: list[CriterionEvaluation] = []
        for ce in verdicts:
            if ce in borderline:
                same_crit = [v for vote in extra_votes for v in vote if v.criterion_id == ce.criterion_id]
                points = [ce.earned_points] + [v.earned_points for v in same_crit]
                median = int(statistics.median(points))
                winner = next((v for v in [ce, *same_crit] if v.earned_points == median), ce)
                reconciled.append(winner)
            else:
                reconciled.append(ce)
        return reconciled
