"""FastAPI-приложение микросервиса оценки работ (EGE & standard tests)."""

from __future__ import annotations

import base64
from functools import lru_cache

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request

from app.config import Settings, get_settings
from app.schemas import AssessmentResult, SubmissionInput
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
