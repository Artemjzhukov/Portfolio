"""FastAPI-приложение микросервиса оценки работ (EGE & standard tests)."""

from __future__ import annotations

import base64
import json
import logging
from functools import lru_cache

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger(__name__)

from app.config import Settings, get_settings
from app.jobs import JobStore, compute_job_id
from app.schemas import (
    AssessmentResult,
    JobAccepted,
    JobStatus,
    SubmissionInput,
)
from app.services.checker_ege import EGEEvaluator
from app.services.llm import OpenAIJSONClient
from app.services.ocr import ExtractionService
from app.services.pipeline import AssessmentPipeline
from app.services.rag import FactChecker, TheoryRetriever

app = FastAPI(
    title="Exam Assessment Service",
    description="Оценка работ учеников (ЕГЭ и стандартные тесты) для n8n -> Notion/Telegram.",
    version="0.1.0",
)


@lru_cache
def _build_pipeline() -> AssessmentPipeline:
    settings = get_settings()
    llm = OpenAIJSONClient(settings, model=settings.openai_eval_model)
    retriever = TheoryRetriever(settings)
    return AssessmentPipeline(
        extraction=ExtractionService(llm=OpenAIJSONClient(settings, model=settings.openai_ocr_model), settings=settings),
        ege_evaluator=EGEEvaluator(llm=llm, settings=settings, factcheck=FactChecker(retriever)),
        retriever=retriever,
    )


def _authorize(x_api_key: str | None, settings: Settings) -> None:
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Неверный X-API-Key")


def _fetch_file(payload: SubmissionInput, settings: Settings) -> tuple[bytes, str | None]:
    if payload.file_bytes:
        try:
            return base64.b64decode(payload.file_bytes, validate=True), payload.file_name
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Некорректный file_bytes: {exc}")
    try:
        resp = httpx.get(payload.file_url or "", timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=400, detail=f"Не удалось скачать файл по file_url: {exc}")
    if len(resp.content) > settings.max_file_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Файл больше лимита max_file_mb")
    return resp.content, payload.file_name


@app.get("/health")
def health() -> dict:
    settings = get_settings()
    retriever = TheoryRetriever(settings)
    return {
        "status": "ok",
        "llm_provider": settings.llm_provider,
        "qdrant_ready": retriever._ensure_ready(),
    }


@app.post("/process-submission", response_model=AssessmentResult)
def process_submission(
    payload: SubmissionInput,
    request: Request,
    x_api_key: str | None = Header(default=None),
) -> AssessmentResult:
    settings = get_settings()
    _authorize(x_api_key, settings)
    file_bytes, file_name = _fetch_file(payload, settings)

    pipeline = _build_pipeline()
    try:
        return pipeline.run(payload, file_bytes, file_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# ---------------------------------------------------------------------------
# Асинхронный путь: n8n не держит соединение на долгую оценку
# ---------------------------------------------------------------------------


@lru_cache
def _get_job_store(db_path: str) -> JobStore:
    return JobStore(db_path)


def _run_job(
    store: JobStore,
    pipeline: AssessmentPipeline,
    job_id: str,
    payload_dict: dict,
    file_bytes: bytes,
    file_name: str | None,
) -> None:
    """Фоновая джоба: результат ИЛИ ошибка всегда попадают в store (никаких тихих пропаж)."""
    store.set_running(job_id)
    try:
        result = pipeline.run(SubmissionInput(**payload_dict), file_bytes, file_name, job_id=job_id)
        store.set_done(job_id, result.model_dump())
    except Exception as exc:  # noqa: BLE001 — ошибка джобы это данные для n8n, не краш
        logger.exception("job=%s pipeline failure", job_id)
        store.set_error(job_id, f"{type(exc).__name__}: {exc}")


@app.post("/process-submission/async")
def process_submission_async(
    payload: SubmissionInput,
    background_tasks: BackgroundTasks,
    x_api_key: str | None = Header(default=None),
):
    settings = get_settings()
    _authorize(x_api_key, settings)
    file_bytes, file_name = _fetch_file(payload, settings)

    job_id = compute_job_id(payload, file_bytes, settings)
    store = _get_job_store(settings.jobs_db_path)
    reused, existing_result = store.create(
        job_id,
        student_id=payload.student_id,
        subject_id=payload.subject_id,
        submission_type=payload.submission_type,
        file_hash=file_bytes.hex()[:32],
    )

    if existing_result is not None:  # уже посчитано — мгновенный ответ, без повторной оплаты LLM
        accepted = JobAccepted(
            job_id=job_id, status="done", reused=True,
            result=AssessmentResult.model_validate(existing_result),
        )
        return json_response(accepted, 200)

    if not reused:
        pipeline = _build_pipeline()
        background_tasks.add_task(
            _run_job, store, pipeline, job_id, payload.model_dump(), file_bytes, file_name
        )
    return json_response(JobAccepted(job_id=job_id, status="queued", reused=reused), 202)


def json_response(model, status_code: int):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status_code, content=model.model_dump(mode="json"))


@app.get("/results/{job_id}", response_model=JobStatus)
def get_result(job_id: str, x_api_key: str | None = Header(default=None)) -> JobStatus:
    settings = get_settings()
    _authorize(x_api_key, settings)
    row = _get_job_store(settings.jobs_db_path).get(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    result = None
    if row["result_json"]:
        result = AssessmentResult.model_validate(json.loads(row["result_json"]))
    return JobStatus(
        job_id=row["job_id"],
        status=row["status"],
        result=result,
        error=row["error"],
        created_at=row["created_at"],
        finished_at=row["finished_at"],
    )
