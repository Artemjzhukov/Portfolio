# Project Log: Exam Assessment Microservice (history-rag)

Chronological decisions, fixes and commits. Product: a FastAPI service that
receives a student submission from n8n, grades it (standard tests & EGE exam),
performs RAG-based gap analysis and returns a structured Russian-language
report for Telegram and Notion.

> This file mirrors `CHANGELOG.md` (Russian). Phase numbering is identical.

---

## Phase 1 — Architecture & Contracts

**Outcome:** `app/` skeleton, Pydantic schemas, first rubric.

- Created the skeleton: `app/schemas.py`, `app/config.py`, `app/services/`,
  `data/criteria/history/task_19.json`, `Dockerfile`, `docker-compose.yml`.
- All Pydantic v2 contracts designed up front: `SubmissionInput` input
  (file_url XOR file_bytes, base64 validator), OCR segments, EGE rubrics with
  **discrete scoring steps** (`deduction_ladder`), LLM evaluations, and the
  output `AssessmentResult`.
- Schema invariants: `sum(criteria.max_points) == max_points`; exactly one
  ladder step equal to `max_points` and one equal to 0 per criterion; unique
  `K*` IDs; duplicate task numbers in OCR segments are forbidden.

**Key decisions (from the /drill-me architecture stress-test):**
1. **Handwriting parsing without sheet structure** — a two-stage approach:
   the vision model only transcribes fragments into JSON (`task_number: null`
   is allowed, guessing is forbidden), while task-number binding and
   cross-page merging are done deterministically in code. Unbound fragments
   are never dropped — they go to `unmatched_segments` and warnings.
2. **Anti-hallucination for EGE point deductions** — strict JSON Schema,
   points may only be chosen from rubric ladder steps, every deduction
   requires a verbatim student quote and a reason, retry on invalid verdicts,
   `needs_human_review` flags plus RAG fact-checking of factual claims
   against the Qdrant corpus (fact-check only adds review flags, never
   changes scores).
3. **Error-free rubric validation** — ladders instead of free-form
   descriptions, Pydantic invariants, `schema_version`/`year_variant` fields.

---

## Phase 2 — Service Implementation

**Outcome:** working end-to-end pipeline, 57 tests, live smoke test.
**Commit:** `5ffb6fd` (27 files).

- `app/services/ocr.py` — file-type detection by magic bytes, pypdf /
  python-docx extraction (including answer-sheet tables), regex task-number
  binding (`№N`, "Задание N", "N."), cross-page segment merging, vision OCR
  with a second verification pass for low-confidence segments.
- `app/services/checker_test.py` — deterministic engine: normalization
  (case, ё→е, punctuation), numbers ("03"="3"), typo fuzzy-match ≥ 0.85,
  sets for multi-choice answers, `Not Submitted` status.
- `app/services/checker_ege.py` — rubric-based LLM evaluator + rubric
  loading with `subject_id` consistency checks.
- `app/services/llm.py` — unified client with retry and JSON mode
  (OpenAI / any OpenAI-compatible / Ollama), `LLMClient` protocol for mocks.
- `app/services/rag.py` — `TheoryRetriever` (lazy init, graceful degradation)
  and `FactChecker`.
- `app/services/pipeline.py` — orchestration + Russian Markdown summary.
- `app/main.py` — `POST /process-submission`, `GET /health`, error handling
  400/413/422/502, optional `X-API-Key` auth.
- Tests (57) written TDD-style: schemas, engines, evaluator with `FakeLLM`,
  API with a mocked pipeline.
- Smoke test `scripts/smoke_test.py`: real request → 2/3 (66.7%), the typo
  "Александр Втрой" accepted, the sheet header captured as a warning.

---

## Phase 3 — Verification & Fixes

- **Fixed a pre-existing SyntaxError in `core/database.py`** (a stray
  `"images"` key outside the `metadata` dict) — the old `main.py` CLI could
  not start at all because of it.
- `.gitignore`: `data/` excluded the rubrics too — now `!data/criteria/`
  (rubrics in git, large data not).
- Second example rubric `social_studies/task_24.json` + a `note` field on
  `TaskRubric` ("example, replace with the official rubric").
- `scripts/smoke_test.py` rewritten with urllib + UTF-8 (PowerShell was
  mangling Cyrillic), stdout forced to UTF-8.
- README: full n8n API contract, rubric format, run instructions, limits.

---

## Phase 4 — n8n-readiness: provider, async, Telegram

**Commits:** `6c2968a` (OpenRouter), `b3d2c24` (async jobs), current (Telegram).

### 4.1 OpenRouter instead of OpenAI
Decision: use OpenRouter keys. Implemented:
- `LLM_BASE_URL=https://openrouter.ai/api/v1` + a regular key — all code
  works through the OpenAI SDK unchanged.
- `LLM_STRICT_JSON=false` — falls back to `json_object` mode with the schema
  embedded in the prompt for models without Structured Outputs (Pydantic
  validation and retry are preserved).
- Models: for EGE grading pick one supporting Structured Outputs; for OCR —
  `openai/gpt-4o` or `google/gemini-2.5-flash`.

### 4.2 Async jobs + idempotency (SQLite for jobs only)
- **The "SQLite vs Qdrant" fork resolved:** Qdrant — semantics (theory,
  fact-check); SQLite — exact keys (jobs, idempotency, audit). A vector DB
  for `WHERE job_id = X` is an anti-pattern.
- The "answer base first → LLM only as fallback" ordering is confirmed and
  already in the core: `standard_test` never calls the LLM; in EGE, part 1
  is deterministic, the LLM only grades part 2. Next step — store answer
  keys inside the service so n8n stops passing `answer_key`.
- `POST /process-submission/async` → 202 + `job_id`;
  `GET /results/{job_id}` → status/result/error. n8n never holds an HTTP
  connection for minutes.
- Idempotency: `job_id = SHA-256(student, subject, type, file, answer key,
  rubric contents)`; a resubmitted POST returns the cached result instantly
  with `reused: true`.
- Jobs stuck in queued/running >20 min are automatically reset; `error`
  jobs re-run on resubmit. SQLite doubles as the audit log (who, when, which
  file, which result/error).
- A background job **always** ends as `done` or `error` in the store — no
  silent losses.

### 4.3 Telegram payloads generated by the service (n8n stays "dumb")
- `telegram_short` (HTML mode, ≤3500 chars): score + top-3 problem tasks
  with truncated reasons. Eliminates the whole "message not delivered"
  failure class (4096 limit, broken MarkdownV2 on arbitrary student text).
- The full report (`summary_feedback`) is sent as a **document**
  (send_document).
- `html_escape()` — user text is safe; n8n sends one message + one document,
  no per-task loops (no 429s).

---

## Phase 5 — Operations (in progress)

### 5.1 Structured logging with `job_id` correlation
- `logging.basicConfig` (INFO) in `app/main.py`; module loggers everywhere.
- Every stage logs with `job=<id>`: job accepted / reused / reset, OCR stats
  (source, pages, segments, unmatched), per-task EGE verdicts, pipeline
  totals, job running/done/error.
- The pipeline's `run()` accepts an optional `job_id` for log correlation;
  failures inside a job are logged with a full traceback (`logger.exception`).
- Test: `job_id` must appear in captured logs of the async flow.

---

## Current State

- **84 tests** (`pytest tests -q`), LLM always mocked, live smoke test OK.
- Commit history: `5ffb6fd` → `6c2968a` → `b3d2c24` → `825c759` → (current).
- All report messages, prompts and deduction reasons are in Russian.

## Backlog (rest of Phase 5, by priority)

1. ✅ **n8n workflow** — done: `n8n/workflow.json` + README instructions
   (webhook → ack → Wait/poll → Telegram → Notion; error branch to
   `TUTOR_CHAT_ID`). Remaining: bind credentials and activate in n8n.
2. **Answer-key storage inside the service** (drop `answer_key` from the
   n8n payload).
3. Fill in the official EGE rubrics (tasks 20–27, other subjects).
4. Optional: `langchain-huggingface` instead of the deprecated
   `langchain-community` embeddings.

## Known Limitations

- Vision OCR of handwriting requires a vision-capable model (OpenRouter:
  gpt-4o / gemini-flash); text-only LLMs are not suitable.
- BackgroundTasks live inside the uvicorn process: a container restart
  during evaluation leaves the job queued until the submission is POSTed
  again (idempotency makes this safe).
- The total score and `percentage` are computed in code — the LLM never
  affects the arithmetic.

