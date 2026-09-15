"""Pydantic v2 модели: входные/выходные payload'ы микросервиса оценки.

Контракт с n8n (вход -> /process-submission -> выход) описан здесь целиком.
Инварианты проверяются на уровне схем, чтобы ошибки валидации нельзя было
«протащить» до недетерминированных компонентов (LLM, RAG).
"""

from __future__ import annotations

import base64
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Литералы
# ---------------------------------------------------------------------------

SubmissionType = Literal["standard_test", "ege_exam"]

# "Not Submitted" — расширение ТЗ: задача отсутствует на листе (нет сегмента).
TaskStatus = Literal["Correct", "Partially Correct", "Incorrect", "Not Submitted"]

SourceType = Literal["pdf_text", "pdf_ocr", "docx", "image_ocr", "plain_text"]


# ---------------------------------------------------------------------------
# Результат распознавания (OCR/извлечение текста)
# ---------------------------------------------------------------------------


class OCRSegment(BaseModel):
    """Один фрагмент ответа ученика, привязанный к номеру задачи (или нет)."""

    model_config = ConfigDict(extra="forbid")

    task_number: Optional[int] = Field(
        default=None, ge=1, le=40,
        description="Номер задачи; null, если определить не удалось (фрагмент уйдёт в unmatched).",
    )
    text: str = Field(..., min_length=1, description="Транскрипция фрагмента ответа.")
    page: int = Field(default=1, ge=1, description="Номер страницы/изображения, где найден фрагмент.")
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="Уверенность распознавания; ниже порога — фрагмент перепроверяется.",
    )
    was_split_across_pages: bool = Field(
        default=False, description="Фрагмент начат на одной странице и продолжен на другой."
    )

    @field_validator("text")
    @classmethod
    def text_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text не может быть пустым или состоять из пробелов")
        return v


class ExtractedSubmission(BaseModel):
    """Полный результат этапа извлечения текста из файла ученика."""

    model_config = ConfigDict(extra="forbid")

    source_type: SourceType
    full_text: str = ""
    segments: list[OCRSegment] = Field(default_factory=list)
    unmatched_segments: list[OCRSegment] = Field(
        default_factory=list,
        description="Фрагменты без номера задачи; НЕ отбрасываются, попадают в отчёт.",
    )
    pages: int = Field(default=1, ge=1)
    ocr_model: Optional[str] = Field(default=None, description="Модель OCR, если применялась.")

    @model_validator(mode="after")
    def unique_task_numbers(self) -> "ExtractedSubmission":
        nums = [s.task_number for s in self.segments if s.task_number is not None]
        if len(nums) != len(set(nums)):
            raise ValueError("дубликаты task_number в segments — шаг merge не был выполнен")
        return self


# ---------------------------------------------------------------------------
# Входной payload от n8n
# ---------------------------------------------------------------------------


class SubmissionInput(BaseModel):
    """Вход микросервиса: файл работы + тип проверки + ключи/метаданные."""

    model_config = ConfigDict(extra="forbid")

    file_url: Optional[str] = Field(default=None, description="URL файла (n8n отдаёт по HTTP).")
    file_bytes: Optional[str] = Field(
        default=None, description="Содержимое файла в base64 (JSON не передаёт сырые байты)."
    )
    file_name: Optional[str] = Field(default=None, description="Имя файла для определения типа, напр. 'work.jpg'.")
    submission_type: SubmissionType
    subject_id: str = Field(..., min_length=2, pattern=r"^[a-z][a-z_]*$", description="Напр. 'history', 'social_studies'.")
    student_id: str = Field(..., min_length=1, description="ID ученика или telegram_chat_id.")
    answer_key: Optional[dict[str, str]] = Field(
        default=None,
        description="Эталонные ответы: номер задачи -> ответ. Обязателен для standard_test; "
        "для ege_exam закрывает часть 1 (короткие ответы).",
    )

    @field_validator("file_bytes")
    @classmethod
    def valid_base64(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            base64.b64decode(v, validate=True)
        except Exception as exc:
            raise ValueError("file_bytes не является корректной base64-строкой") from exc
        return v

    @model_validator(mode="after")
    def exactly_one_file_source(self) -> "SubmissionInput":
        if bool(self.file_url) == bool(self.file_bytes):
            raise ValueError("нужен ровно один источник файла: file_url ИЛИ file_bytes")
        return self

    @model_validator(mode="after")
    def standard_test_requires_key(self) -> "SubmissionInput":
        if self.submission_type == "standard_test" and not self.answer_key:
            raise ValueError("для standard_test обязателен answer_key (эталонные ответы)")
        return self



# ---------------------------------------------------------------------------
# Рубрики ЕГЭ (data/criteria/{subject}/task_{N}.json)
# ---------------------------------------------------------------------------


class DeductionStep(BaseModel):
    """Дискретная ступень снижения балла по критерию."""

    model_config = ConfigDict(extra="forbid")

    points: int = Field(..., ge=0, description="Сколько баллов заработано на этой ступени.")
    condition_ru: str = Field(..., min_length=1, description="Условие ступени (для промпта оценщика).")


class RubricCriterion(BaseModel):
    """Один критерий рубрики ЕГЭ (K1, K2, ...)."""

    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(..., pattern=r"^K\d+$")
    title_ru: str = Field(..., min_length=1)
    description_ru: str = Field(..., min_length=1)
    max_points: int = Field(..., gt=0)
    deduction_ladder: list[DeductionStep] = Field(
        ..., min_length=2,
        description="Дискретные ступени: оценщик выбирает ступень, а не придумывает балл.",
    )
    factcheck_topics: list[str] = Field(
        default_factory=list,
        description="Темы для фактчек-запроса в Qdrant, если балл снижен.",
    )

    @model_validator(mode="after")
    def ladder_matches_max(self) -> "RubricCriterion":
        pts = [s.points for s in self.deduction_ladder]
        if pts.count(self.max_points) != 1:
            raise ValueError(f"{self.criterion_id}: ступень с points == max_points должна быть ровно одна")
        if min(pts) != 0:
            raise ValueError(f"{self.criterion_id}: должна быть ступень с points == 0")
        if len(pts) != len(set(pts)):
            raise ValueError(f"{self.criterion_id}: дубликаты ступеней в deduction_ladder")
        return self

    def ladder_text(self) -> str:
        """Таблица ступеней для промпта LLM-оценщика."""
        return "\n".join(f"  {s.points} балл(а): {s.condition_ru}" for s in self.deduction_ladder)


class TaskRubric(BaseModel):
    """Полная рубрика одного задания ЕГЭ."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    subject_id: str = Field(..., min_length=2, pattern=r"^[a-z][a-z_]*$")
    task_number: int = Field(..., ge=1, le=40)
    year_variant: str = Field(default="2025")
    max_points: int = Field(..., gt=0)
    part: Literal[1, 2]
    note: Optional[str] = Field(
        default=None, description="Произвольная пометка, напр. 'пример, заменить официальной рубрикой'."
    )
    criteria: list[RubricCriterion] = Field(..., min_length=1)

    @model_validator(mode="after")
    def sum_matches(self) -> "TaskRubric":
        total = sum(c.max_points for c in self.criteria)
        if total != self.max_points:
            raise ValueError(f"sum(criteria.max_points)={total} != task max_points={self.max_points}")
        ids = [c.criterion_id for c in self.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("дубликаты criterion_id в рубрике")
        return self

    def criterion(self, criterion_id: str) -> RubricCriterion:
        for c in self.criteria:
            if c.criterion_id == criterion_id:
                return c
        raise KeyError(f"критерий {criterion_id} отсутствует в задании {self.task_number}")



# ---------------------------------------------------------------------------
# Оценка LLM по критериям
# ---------------------------------------------------------------------------


class CriterionEvaluation(BaseModel):
    """Вердикт LLM по одному критерию."""

    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(..., pattern=r"^K\d+$")
    earned_points: int = Field(..., ge=0)
    quote_from_answer: str = Field(
        default="",
        description="Дословная цитата из ответа ученика, подтверждающая снижение балла.",
    )
    deduction_reason_ru: str = Field(
        default="", description="Причина снижения на русском; пусто, если балл не снижен."
    )


def validate_evaluation(ce: CriterionEvaluation, crit: RubricCriterion) -> None:
    """Проверка вердикта против рубрики. Raises ValueError."""
    if ce.earned_points > crit.max_points:
        raise ValueError(f"{crit.criterion_id}: earned_points > max_points")
    if ce.earned_points not in {s.points for s in crit.deduction_ladder}:
        raise ValueError(f"{crit.criterion_id}: балл {ce.earned_points} вне ступеней рубрики")
    deducted = crit.max_points - ce.earned_points
    if deducted > 0:
        if not ce.deduction_reason_ru.strip():
            raise ValueError(f"{crit.criterion_id}: снижение требует обоснования")
        if not ce.quote_from_answer.strip():
            raise ValueError(f"{crit.criterion_id}: снижение требует дословной цитаты из ответа")
    else:
        if ce.deduction_reason_ru.strip():
            raise ValueError(f"{crit.criterion_id}: при полном соответствии обоснование не допускается")


class EGEEvaluation(BaseModel):
    """Итог оценки одного задания ЕГЭ (после валидации и санити-чеков)."""

    model_config = ConfigDict(extra="forbid")

    task_number: int
    criteria_evaluations: list[CriterionEvaluation] = Field(default_factory=list)
    needs_human_review: bool = False
    review_reasons_ru: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_criteria(self) -> "EGEEvaluation":
        ids = [e.criterion_id for e in self.criteria_evaluations]
        if len(ids) != len(set(ids)):
            raise ValueError("дубликаты criterion_id в оценке")
        return self

    def earned(self, rubric: TaskRubric) -> int:
        by_id = {e.criterion_id: e for e in self.criteria_evaluations}
        return sum(by_id[c.criterion_id].earned_points for c in rubric.criteria if c.criterion_id in by_id)


# ---------------------------------------------------------------------------
# RAG-рекомендации
# ---------------------------------------------------------------------------


class RAGChunk(BaseModel):
    text: str
    source: Optional[str] = None
    topic: Optional[str] = None
    score: float = Field(default=0.0, ge=0.0, le=1.0)


class RAGRecommendation(BaseModel):
    task_number: Union[int, str]
    query_text: str = ""
    chunks: list[RAGChunk] = Field(default_factory=list)
    recommended_topics: str = Field(
        default="", description="Готовое к отправке действие на русском (markdown)."
    )
    unavailable_reason: str = Field(
        default="", description="Заполнено, если Qdrant/эмбеддинги недоступны — оценка не падает."
    )


# ---------------------------------------------------------------------------
# Итоговый payload для Notion / Telegram
# ---------------------------------------------------------------------------


class TaskBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_number: Union[int, str]
    max_points: int = Field(..., ge=0)
    earned_points: int = Field(..., ge=0)
    status: TaskStatus
    student_answer: str = ""
    correct_answer_or_criteria: str = ""
    deduction_reason: str = ""
    recommended_topics: str = ""
    needs_human_review: bool = False


def derive_status(earned: int, max_points: int) -> TaskStatus:
    if max_points > 0 and earned == max_points:
        return "Correct"
    if earned > 0:
        return "Partially Correct"
    return "Incorrect"


class AssessmentResult(BaseModel):
    """Ответ микросервиса для n8n (далее -> Notion + Telegram)."""

    model_config = ConfigDict(extra="forbid")

    student_id: str
    subject_id: str
    submission_type: SubmissionType
    total_score: float = Field(..., ge=0)
    max_possible_score: float = Field(..., ge=0)
    percentage: float = Field(..., ge=0.0, le=100.0)
    summary_feedback: str = Field(..., description="Markdown-обзор на русском.")
    task_breakdown: list[TaskBreakdown] = Field(default_factory=list)
    needs_human_review: bool = False
    warnings: list[str] = Field(
        default_factory=list,
        description="Напр. непривязанные фрагменты ответов, недоступный Qdrant.",
    )

    @model_validator(mode="after")
    def recompute_percentage(self) -> "AssessmentResult":
        if self.max_possible_score > 0:
            self.percentage = round(self.total_score / self.max_possible_score * 100, 1)
        else:
            self.percentage = 0.0
        return self


# ---------------------------------------------------------------------------
# Асинхронные джобы (n8n не ждёт: webhook -> 202 -> опрос /results/{job_id})
# ---------------------------------------------------------------------------


class JobAccepted(BaseModel):
    """Ответ на POST /process-submission/async."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: Literal["queued", "running", "done"]
    reused: bool = Field(
        default=False,
        description="true = тот же submission уже обрабатывался; повторной оплаты LLM нет.",
    )
    result: Optional[AssessmentResult] = None


class JobStatus(BaseModel):
    """Ответ на GET /results/{job_id}."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: Literal["queued", "running", "done", "error"]
    result: Optional[AssessmentResult] = None
    error: Optional[str] = None
    created_at: Optional[float] = None
    finished_at: Optional[float] = None

