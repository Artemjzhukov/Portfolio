"""Единая точка доступа к LLM: JSON-режим, retry, валидация формата.

Все промпты — на русском (требование проекта). Классы реализуют протокол
LLMClient, что позволяет подменять их фейками в тестах (TDD).
"""

from __future__ import annotations

import json
import re
from typing import Protocol, Sequence, Union

from openai import OpenAI

from app.config import Settings


class LLMError(RuntimeError):
    """Ошибка вызова внешнего LLM (сеть, 5xx, таймаут)."""


class LLMOutputError(LLMError):
    """LLM доступна, но вернула невалидный JSON после всех попыток."""


class LLMClient(Protocol):
    def chat(
        self,
        *,
        system: str,
        user: Union[str, Sequence[dict]],
        schema: dict,
        schema_name: str,
    ) -> dict: ...


def _strip_json_fences(raw: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
    return match.group(1) if match else raw


class OpenAIJSONClient:
    """OpenAI (или OpenAI-совместимый сервер, напр. Ollama) со строгим JSON-выходом.

    - provider=openai: response_format = json_schema (strict) — схема навязывается API.
    - provider=ollama: json_object режим + текст схемы в промпте + парсинг.
    """

    def __init__(self, settings: Settings, *, model: str | None = None) -> None:
        self.strict = settings.llm_provider == "openai"
        base_url = f"{settings.ollama_base_url.rstrip('/')}/v1" if not self.strict else None
        self._client = OpenAI(
            api_key=settings.openai_api_key or "not-set",
            base_url=base_url,
        )
        if model:
            self.model = model
        elif self.strict:
            self.model = settings.openai_eval_model
        else:
            self.model = settings.ollama_model

    def chat(
        self,
        *,
        system: str,
        user: Union[str, Sequence[dict]],
        schema: dict,
        schema_name: str,
        temperature: float = 0.0,
        max_retries: int = 2,
    ) -> dict:
        if not self.strict:
            system = (
                f"{system}\n\nВерни строго валидный JSON по схеме:\n"
                f"{json.dumps(schema, ensure_ascii=False)}"
            )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user if isinstance(user, str) else list(user)},
        ]

        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            response_format = (
                {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}}
                if self.strict
                else {"type": "json_object"}
            )
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    response_format=response_format,
                )
                raw = resp.choices[0].message.content or ""
            except Exception as exc:  # сеть, 429, 5xx
                last_error = exc
                continue
            try:
                return json.loads(_strip_json_fences(raw))
            except json.JSONDecodeError as exc:
                last_error = exc

        if isinstance(last_error, json.JSONDecodeError):
            raise LLMOutputError(f"LLM вернула невалидный JSON после {max_retries + 1} попыток: {last_error}")
        raise LLMError(f"Ошибка вызова LLM: {last_error}")
