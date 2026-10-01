"""Pydantic v2 модели: входные/выходные payload'ы микросервиса оценки.

Контракт с n8n (вход -> /process-submission -> выход) описан здесь целиком.
Инварианты проверяются на уровне схем, чтобы ошибки валидации нельзя было
«протащить» до недетерминированных компонентов (LLM, RAG).
"""

from __future__ import annotations

import base64
import re
import time
from datetime import datetime, timezone
from enum import Enum
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
    test_name: Optional[str] = Field(
        default=None, min_length=1, max_length=200,
        description="Название теста (напр. 'Вариант 3'); если пусто — '{subject_id} · {дата оценки}'.",
    )
    answer_key: Optional[dict[str, str]] = Field(
        default=None,
        description="Эталонные ответы: номер задачи -> ответ. Опционально: если не заданы, "
        "берутся из data/answer_keys/{subject_id}.json (файл побеждает только при пустом payload).",
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
    image: Optional[str] = Field(
        default=None, description="Относительный путь к изображению (data/media), если чанк — иллюстрация."
    )


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


class AnswerKeyFile(BaseModel):
    """Файл эталонных ответов теста: data/answer_keys/{subject_id}.json."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    subject_id: str = Field(..., min_length=2, pattern=r"^[a-z][a-z_]*$")
    answers: dict[str, str] = Field(..., description="Номер задачи -> правильный ответ.")
    note: Optional[str] = Field(default=None, description="Пометка, напр. 'пример, замените реальными ключами'.")


class AssessmentResult(BaseModel):
    """Ответ микросервиса для n8n (далее -> Notion + Telegram)."""

    model_config = ConfigDict(extra="forbid")

    student_id: str
    subject_id: str
    submission_type: SubmissionType
    total_score: float = Field(..., ge=0)
    max_possible_score: float = Field(..., ge=0)
    percentage: float = Field(..., ge=0.0, le=100.0)
    summary_feedback: str = Field(..., description="Markdown-обзор на русском (полный отчёт: Notion + файл в Telegram).")
    telegram_short: str = Field(
        default="",
        description="Короткое HTML-сообщение для Telegram (<=3500 знаков): балл + топ-проблемные задания.",
    )
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


# ---------------------------------------------------------------------------
# Дашборд ученика, Notion-синк и Telegram (фаза: прогресс и оценка)
# ---------------------------------------------------------------------------


class TopicMastery(str, Enum):
    """Статус освоения темы в roadmap дашборда."""

    LEARNED = "learned"
    NEEDS_REVIEW = "needs_review"
    PENDING = "pending"


TOPIC_MASTERY_RU: dict[str, str] = {
    TopicMastery.LEARNED.value: "Изучено",
    TopicMastery.NEEDS_REVIEW.value: "Нужно повторить",
    TopicMastery.PENDING.value: "В планах",
}

TASK_STATUS_RU: dict[str, str] = {
    "Correct": "Верно",
    "Partially Correct": "Частично верно",
    "Incorrect": "Неверно",
    "Not Submitted": "Не сдано",
}

SUBMISSION_TYPE_RU: dict[str, str] = {
    "standard_test": "стандартный тест",
    "ege_exam": "ЕГЭ",
}

MEDIA_URL_PREFIX = "/media/"

_URL_RE = re.compile(r"^(https?://\S+|/media/\S+)$")
_HTTP_URL_RE = re.compile(r"^https?://\S+$")


def build_test_title(subject_id: str, evaluated_at: float, test_name: str | None = None) -> str:
    """Название теста: явное test_name либо "subject · YYYY-MM-DD" (UTC)."""
    name = (test_name or "").strip()
    if name:
        return name
    day = datetime.fromtimestamp(evaluated_at, tz=timezone.utc).strftime("%Y-%m-%d")
    return f"{subject_id} · {day}"


class EvaluationRecord(BaseModel):
    """Строка таблицы results: что сохраняем из AssessmentResult (без повторного LLM)."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(..., min_length=1)
    student_id: str = Field(..., min_length=1)
    subject_id: str = Field(..., min_length=2, pattern=r"^[a-z][a-z_]*$")
    submission_type: SubmissionType
    test_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    test_title: str = Field(..., min_length=1, max_length=200)
    total_score: float = Field(..., ge=0)
    max_possible_score: float = Field(..., ge=0)
    percentage: float = Field(..., ge=0.0, le=100.0)
    task_breakdown: list[TaskBreakdown] = Field(default_factory=list)
    needs_human_review: bool = False
    evaluated_at: float = Field(default_factory=time.time, ge=0)

    @model_validator(mode="after")
    def _recompute_percentage(self) -> "EvaluationRecord":
        if self.max_possible_score > 0:
            self.percentage = round(self.total_score / self.max_possible_score * 100, 1)
        else:
            self.percentage = 0.0
        return self

    @classmethod
    def from_assessment(
        cls,
        job_id: str,
        result: AssessmentResult,
        *,
        test_name: str | None = None,
        evaluated_at: float | None = None,
    ) -> "EvaluationRecord":
        """Единственная точка маппинга AssessmentResult -> строка results."""
        ts = evaluated_at if evaluated_at is not None else time.time()
        return cls(
            job_id=job_id,
            student_id=result.student_id,
            subject_id=result.subject_id,
            submission_type=result.submission_type,
            test_name=test_name,
            test_title=build_test_title(result.subject_id, ts, test_name),
            total_score=result.total_score,
            max_possible_score=result.max_possible_score,
            percentage=result.percentage,
            task_breakdown=result.task_breakdown,
            needs_human_review=result.needs_human_review,
            evaluated_at=ts,
        )


class DashboardTestItem(BaseModel):
    """Одна работа в истории дашборда (последние N)."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(..., min_length=1)
    test_title: str = Field(..., min_length=1, max_length=200)
    submission_type: SubmissionType
    total_score: float = Field(..., ge=0)
    max_possible_score: float = Field(..., ge=0)
    percentage: float = Field(..., ge=0.0, le=100.0)
    evaluated_at: float = Field(..., ge=0)
    needs_human_review: bool = False

    @model_validator(mode="after")
    def _recompute_percentage(self) -> "DashboardTestItem":
        if self.max_possible_score > 0:
            self.percentage = round(self.total_score / self.max_possible_score * 100, 1)
        else:
            self.percentage = 0.0
        return self



class DashboardTaskItem(BaseModel):
    """Детализация одного задания в дашборде."""

    model_config = ConfigDict(extra="forbid")

    task_number: Union[int, str]
    earned_points: int = Field(..., ge=0)
    max_points: int = Field(..., ge=0)
    status: TaskStatus
    deduction_reason_ru: str = Field(default="", max_length=2000)
    topics_to_review_ru: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _status_consistent(self) -> "DashboardTaskItem":
        earned, maximum = self.earned_points, self.max_points
        if earned > maximum:
            raise ValueError("earned_points не может превышать max_points")
        if maximum > 0 and earned == maximum:
            expected = ("Correct",)
        elif earned > 0:
            expected = ("Partially Correct",)
        else:
            expected = ("Incorrect", "Not Submitted")
        if self.status not in expected:
            raise ValueError(f"статус {self.status!r} не согласуется с баллами {earned}/{maximum}")
        return self


class DashboardTopicItem(BaseModel):
    """Строка roadmap: тема и статус освоения."""

    model_config = ConfigDict(extra="forbid")

    topic_ru: str = Field(..., min_length=1, max_length=200)
    status: TopicMastery
    source: str = Field(default="", max_length=120, description="Откуда выведено: RAG, ошибки заданий, эксперт.")


class MaterialLink(BaseModel):
    """Ссылка на материал: /media/... или внешний URL."""

    model_config = ConfigDict(extra="forbid")

    title_ru: str = Field(..., min_length=1, max_length=200)
    url: str = Field(..., min_length=1, max_length=2000)
    kind: Literal["pdf", "file", "link"] = "file"

    @field_validator("url")
    @classmethod
    def _url_allowed(cls, v: str) -> str:
        if not _URL_RE.match(v):
            raise ValueError("url должен быть https://... или /media/...")
        return v

    @model_validator(mode="after")
    def _pdf_matches_kind(self) -> "MaterialLink":
        if self.kind == "pdf":
            path = self.url.split("?", 1)[0].split("#", 1)[0]
            if not path.lower().endswith(".pdf"):
                raise ValueError("kind='pdf' требует url на .pdf")
        return self


class StudentDashboard(BaseModel):
    """Полный payload GET /dashboard/{student_id}."""

    model_config = ConfigDict(extra="forbid")

    student_id: str = Field(..., min_length=1)
    overall_score: float = Field(..., ge=0)
    pass_rate: float = Field(..., ge=0.0, le=100.0)
    covered_topics_count: int = Field(..., ge=0)
    total_tests_count: int = Field(..., ge=0, description="Накопительный счётчик всех работ.")
    recent_tests: list[DashboardTestItem] = Field(default_factory=list, max_length=10)
    tasks: list[DashboardTaskItem] = Field(default_factory=list)
    roadmap: list[DashboardTopicItem] = Field(default_factory=list)
    materials: list[MaterialLink] = Field(default_factory=list)

    @model_validator(mode="after")
    def _totals_consistent(self) -> "StudentDashboard":
        if self.total_tests_count < len(self.recent_tests):
            raise ValueError("total_tests_count меньше числа recent_tests")
        return self


class NotionSyncPayload(BaseModel):
    """Строка Notion CRM учителя (синк — только фоном, не блокирует API)."""

    model_config = ConfigDict(extra="forbid")

    student_name: str = Field(..., min_length=1, max_length=200)
    test_title: str = Field(..., min_length=1, max_length=200)
    score: float = Field(..., ge=0)
    percentage: float = Field(..., ge=0.0, le=100.0)
    date: str = Field(..., description="Дата в ISO-8601.")
    dashboard_url: str = Field(..., description="Ссылка на дашборд ученика.")
    job_id: str = Field(..., min_length=1)
    needs_human_review: bool = False

    @field_validator("date")
    @classmethod
    def _iso_date(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("date должен быть строкой ISO-8601") from exc
        return v

    @field_validator("dashboard_url")
    @classmethod
    def _http_url(cls, v: str) -> str:
        if not _HTTP_URL_RE.match(v):
            raise ValueError("dashboard_url должен быть https://...")
        return v


class TelegramResultMessage(BaseModel):
    """Быстрый ответ ученику в Telegram (лимит 4096 знаков)."""

    model_config = ConfigDict(extra="forbid")

    chat_id: str = Field(..., min_length=1, max_length=64, pattern=r"^\S+$")
    text_ru: str = Field(..., min_length=1, max_length=4096)
    dashboard_url: str = Field(..., description="Ссылка на детальный разбор.")
    parse_mode: Literal["HTML"] = "HTML"

    @field_validator("dashboard_url")
    @classmethod
    def _http_url(cls, v: str) -> str:
        if not _HTTP_URL_RE.match(v):
            raise ValueError("dashboard_url должен быть https://...")
        return v


class DashboardTokenIssue(BaseModel):
    """Запрос на выпуск одноразовой ссылки (команда /dashboard)."""

    model_config = ConfigDict(extra="forbid")

    student_id: str = Field(..., min_length=1)
    telegram_chat_id: str = Field(..., min_length=1, max_length=64, pattern=r"^\S+$")
    ttl_hours: int = Field(default=72, ge=1, le=720)


class DashboardTokenRecord(BaseModel):
    """Строка таблицы dashboard_tokens (храним только хэш токена)."""

    model_config = ConfigDict(extra="forbid")

    token_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    student_id: str = Field(..., min_length=1)
    telegram_chat_id: str = Field(..., min_length=1, max_length=64)
    created_at: float = Field(..., ge=0)
    expires_at: float = Field(..., ge=0)
    used: bool = False

    @model_validator(mode="after")
    def _expiry_after_creation(self) -> "DashboardTokenRecord":
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at должен быть позже created_at")
        return self


class DashboardAccessQuery(BaseModel):
    """Параметр ?token=... эндпоинта дашборда."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., min_length=20, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
