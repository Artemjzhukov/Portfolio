# Local Knowledge Assistant (RAG) — Design Notes

## Status
In progress. Current corpus: 5000 documents, 15000 pages, Russian.

## Architecture Decisions
- **Chunking**:D ocuments are currently added to the vector store without splitting. Planned: RecursiveCharacterTextSplitter  
  (~500 tokens, 15% overlap), structure-aware where possible. Rationale: preserves semantic units in historical narratives, avoids splitting events mid-chunk.  
- **Embeddings**: HuggingFace — chosen for Russian/English.
- **Vector Store**: Qdrant (Docker) — cosine similarity, top-k=5.
- **Generation**: Llama 3 8B via Ollama, quantized Q4/Q5 for local 
  inference speed.
- **Hallucination mitigation**: strict context-grounded system prompt + 
  source citation return.

## Why fully local
Source materials are privacy-sensitive (tutor-owned historical archives); 
zero external API calls is a hard requirement, not a default preference.

## Known Gaps (in progress)  
- **Vector dimension conflict handling**: not yet automated. Collection is created only if absent; changing the embedding model requires manual  
  collection recreation. Planned: compare existing collection's vector size against the active embedding model at startup, and either version   
  the collection name or raise an explicit, actionable error.  
- **Pydantic validation**: not yet implemented. Planned: a document schema (content, source, date, topic) validated before ingestion.  
- **Source citations**: format_docs currently concatenates raw page_content with no metadata; answers can't currently cite which document/chunk was used.  
- **Cross-machine portability**: currently relies on localhost defaults for Qdrant/Ollama; environment-variable config exists (QDRANT_HOST, OLLAMA_URL)  
  but hasn't been tested end-to-end on a genuinely separate client/server setup.  
- **Retrieval**: dense-only (top-k=3), no hybrid/BM25, no reranking, no similarity-score threshold — low-relevance results are currently filtered  
  only via the system prompt, not programmatically.  
- **No conversation memory** — each query is stateless.

    
- planned: RAGAS
- Reindexing currently full-batch; incremental upsert planned as corpus grows.

---

# Микросервис оценки работ (EGE & Standard Tests)

FastAPI-сервис в `app/`: принимает работу ученика от n8n, распознаёт текст
(PDF/DOCX напрямую, изображения/сканы — Vision OCR), проверяет и возвращает
структурированный отчёт на русском для Notion/Telegram.

## API

### `POST /process-submission`

Вход (JSON):

```json
{
  "file_bytes": "<base64>",              // ИЛИ "file_url": "https://..."
  "file_name": "work.jpg",               // опционально, помогает определить тип
  "submission_type": "standard_test",    // "standard_test" | "ege_exam"
  "subject_id": "history",               // имя папки рубрик в data/criteria/
  "student_id": "tg_12345",              // telegram_chat_id
  "answer_key": {"1": "3", "2": "5"}     // обязателен для standard_test; для EGE закрывает часть 1
}
```

Выход — `AssessmentResult`: `total_score`, `max_possible_score`, `percentage`,
`summary_feedback` (Markdown, русский), `task_breakdown[]` (`status`:
`Correct | Partially Correct | Incorrect | Not Submitted`, `deduction_reason`,
`recommended_topics` из RAG), `needs_human_review`, `warnings[]`.

Авторизация: если в `.env` задан `API_KEY`, запрос должен содержать заголовок
`X-API-Key: <значение>`.

### `GET /health`

`{"status": "ok", "llm_provider": "...", "qdrant_ready": bool}`

### Асинхронный путь (рекомендуется для n8n)

Полная оценка ЕГЭ занимает минуты — n8n не должен ждать по HTTP. Схема:
webhook → `POST /process-submission/async` → мгновенный ack в Telegram →
опрос → отправка отчёта.

```
POST /process-submission/async          # 202 {"job_id", "status": "queued", "reused"}
GET  /results/{job_id}                  # {"status": "queued|running|done|error", "result": {...}}
```

- Повторный POST того же submission (ученик + файл + ключи + рубрики) →
  **мгновенный 200 с готовым результатом** и `reused: true` — двойной оплаты
  LLM и дубликатов в Notion нет (идемпотентность по SHA-256 входа).
- Джобы хранятся в SQLite (`JOBS_DB_PATH`, по умолчанию
  `assessment_jobs.db`) — это же и audit log: кто, когда, с каким файлом,
  с каким результатом/ошибкой. Зависшая (>20 мин) queued/running джоба
  автоматически перезапускается; `error`-джоба перезапускается при повторном
  POST.

## Как оценивается

- **standard_test** — детерминированно: нормализация (регистр, ё→е, пунктуация,
  числа «03»=«3»), толерантность к опечаткам (fuzzy ≥ 0.85), множества для
  мультивыбора («1,3,4» = «4,1,3»). Баллы бинарные.
- **ege_exam** — часть 1 по `answer_key`; часть 2 по рубрикам
  `data/criteria/{subject}/task_{N}.json` через LLM со строгим JSON-выходом.
  Балл LLM выбирает только из дискретных ступеней рубрики
  (`deduction_ladder`), любое снижение требует дословной цитаты из ответа и
  причины; спорные оценки помечаются `needs_human_review` и идут на ручную
  проверку (Notion). Критерии с `factcheck_topics` дополнительно проверяются
  по хранилищу Qdrant.

## Рубрики

Формат — `TaskRubric` из `app/schemas.py`. Инварианты, проверяемые Pydantic:
`sum(criteria.max_points) == max_points`, у каждого критерия ровно одна
ступень с `points == max_points` и одна с `points == 0`, уникальные `K*`-ID.
Включённые файлы (`history/task_19.json`, `social_studies/task_24.json`) —
**примеры**: перед продакшеном замените официальными рубриками нужного года.

## Запуск

```bash
docker compose up --build        # FastAPI на :8000, Qdrant на :6333
# локально:
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

Тесты: `.venv\Scripts\python -m pytest tests -q` (57 тестов, LLM замокан).
Смоук-тест: поднять сервер и выполнить `.venv\Scripts\python scripts\smoke_test.py`.

## Настройки (.env)

`LLM_PROVIDER=openai|ollama`, `OPENAI_API_KEY`, `OPENAI_EVAL_MODEL`,
`OPENAI_OCR_MODEL` (Vision OCR рукописей требует OpenAI: Llama/llava
недостаточны для строгой транскрипции), `QDRANT_HOST/PORT/COLLECTION`,
`CONSISTENCY_VOTES` (медиана из N голосов для спорных критериев),
`OCR_CONFIDENCE_THRESHOLD`, `RAG_TOP_K`, `API_KEY`.

### OpenRouter вместо OpenAI

Любой OpenAI-совместимый провайдер работает через `LLM_BASE_URL`:

```env
LLM_PROVIDER=openai
LLM_BASE_URL=https://openrouter.ai/api/v1
OPENAI_API_KEY=sk-or-v1-...
OPENAI_EVAL_MODEL=openai/gpt-4o
OPENAI_OCR_MODEL=openai/gpt-4o
LLM_STRICT_JSON=false   # если модель не поддерживает Structured Outputs
```

При `LLM_STRICT_JSON=false` сервис переключается на `json_object`-режим:
схема встраивается в промпт, ответ валидируется Pydantic и при невалидном
JSON повторяется запрос (retry) — защита от галлюцинаций сохраняется.

## Известные ограничения

- Vision OCR — только через OpenAI; при `LLM_PROVIDER=ollama` изображения и
  сканы возвращают ошибку 502 с понятным сообщением.
- `percentage` и статусы считаются кодом, LLM не влияет на подсчёт итогов.
- Файлы > `MAX_FILE_MB` по `file_url` отклоняются с 413.

### Telegram-отправка

Ответ содержит готовые пейлоады:
- `telegram_short` — короткое HTML-сообщение (≤3500 знаков): балл + топ-3
  проблемных задания. Отправлять с `parse_mode=HTML`.
- `summary_feedback` — полный отчёт; отправлять **файлом** (send_document),
  а не сообщением.

Историю решений и правок по фазам см. `CHANGELOG.md` (рус.) и
`CHANGELOG_EN.md` (англ.). Логи: каждый этап пишет `job=<id>` (docker logs).

