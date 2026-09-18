"""Конфигурация микросервиса (pydantic-settings, читает .env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Qdrant / эмбеддинги (совместимы с core/database.py) ---
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "history_docs"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    # --- LLM ---
    # openai: strict JSON Schema + Vision OCR. ollama: локальный OpenAI-совместимый сервер.
    # Любой OpenAI-совместимый провайдер (напр. OpenRouter) — через llm_base_url.
    llm_provider: Literal["openai", "ollama"] = "openai"
    openai_api_key: str = ""
    llm_base_url: str = Field(
        default="",
        description="OpenAI-совместимый endpoint, напр. https://openrouter.ai/api/v1. Пусто = api.openai.com.",
    )
    llm_strict_json: bool = Field(
        default=True,
        description="Strict JSON Schema (Structured Outputs). Для провайдеров без поддержки (часть моделей OpenRouter) — false: json_object + схема в промпте.",
    )
    openai_eval_model: str = "gpt-4o"      # оценка ЕГЭ по критериям
    openai_ocr_model: str = "gpt-4o"       # распознавание почерка (нужна Vision-модель)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3:8b"

    # --- Извлечение текста ---
    min_extracted_chars: int = 40          # меньше текста в PDF -> считаем сканом -> OCR
    ocr_confidence_threshold: float = 0.6  # ниже — сегмент перепроверяется вторым проходом
    max_file_mb: int = 25

    @property
    def ocr_is_vision_capable(self) -> bool:
        return self.llm_provider == "openai"

    # --- Оценка ЕГЭ ---
    consistency_votes: int = 1             # >1: медиана из N голосов для спорных критериев
    criteria_dir: Path = Path("data/criteria")
    answer_keys_dir: Path = Path("data/answer_keys")  # эталоны: {subject_id}.json

    # --- RAG-рекомендации ---
    rag_top_k: int = 5
    rag_min_score: float = 0.35            # ниже — чанк считается нерелевантным

    # --- API ---
    api_key: str = ""                      # shared secret для n8n; пусто = авторизация выключена
    jobs_db_path: str = "assessment_jobs.db"  # SQLite store джоб (idempotency/аудит)


@lru_cache
def get_settings() -> Settings:
    return Settings()
