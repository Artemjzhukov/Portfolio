# English-Tutor Bot — Phase 4 Audit Report (excerpt)

**Commit audited:** `ddab7ca746a4ea2d5e69cd2283492088fd1d91bb` (main)
**Status:** 171 tests green, `ruff` clean. Live test run confirmed: `171 passed in 89.18s`.

---

## 1. Architecture Overview

### Stack (as declared in `pyproject.toml`)
| Layer | Technology | Notes |
|---|---|---|
| Bot framework | `aiogram` ≥3.13 | v3.x handler/router pattern; `dp.workflow_data` for DI |
| LLM inference | `groq` ≥0.11 | `openai/gpt-oss-120b` (text), `whisper-large-v3` (ASR) |
| Persistence | raw `sqlite3` (stdlib) | connection-per-operation, `row_factory = Row`, `PRAGMA foreign_keys = ON` |
| Audio | Telegram Bot API `bot.download` → temp `.ogg` → Whisper | `services/voice.py`-equivalent logic in `handlers/voice.py:save_and_transcribe` |
| Containerization | Docker (Python 3.12-slim) + `compose.yaml` | `DB_PATH → /app/data/tutor.db`, volume-mounted |
| Test | `pytest` + `pytest-asyncio` (auto mode) | 171 tests, `tmp_path`-based SQLite fixtures |

> ⚠️ **Deployment gap** (`SPEC.md` §21, item 12 / README line 25): The `Dockerfile` and `compose.yaml` exist on disk, but `SPEC.md` still labels Docker as "Phase 4 / deferred". The runtime wiring is **in place** (`main.py` → `GroqService` → `connect(config.db_path)`), yet nothing in the codebase or CI guards the Docker build path. **No GitHub Actions workflow** was found in `.github/` to exercise the container build or run tests in CI (the `ruff` CI step listed as "still open" in SPEC §21 item 11 is **not** configured in-repo).

### Module map (source of several audit mis-locations)
The Phase 4 plan (`docs/superpowers/plans/2026-09-16-phase4.md`) and several code comments reference modules that do **not** exist at the paths implied:

| Referenced path | Actual location |
|---|---|
| `english_tutor/services/llm.py` | `english_tutor/llm/groq_service.py` (`GroqService`) |
| `english_tutor/services/whisper.py` | `english_tutor/handlers/voice.py` (`save_and_transcribe`) |
| `english_tutor/services/reminders.py` | `english_tutor/scheduler.py` |
| `english_tutor/handlers/reminders.py` | `english_tutor/scheduler.py` (no router) |
| `english_tutor/services/admin.py` | `english_tutor/handlers/admin.py` |
| `english_tutor/llm/groq.py` (SPEC glossary) | `english_tutor/llm/groq_service.py` |
| `english_tutor/models.py` | does **not exist** (no ORM; plain `sqlite3.Row` dicts) |
| `english_tutor/services/exercises.normalize` (used by stories) | `english_tutor/services/exercises.py` ✅ |

This is a **documentation drift** risk: the SPEC and plan reference logical module names that have been consolidated/refactored. New contributors following the plan's file paths will not find the described code. **Recommendation:** update `docs/superpowers/plans/2026-09-16-phase4.md` line 11 and SPEC §15 references to match the real paths.

---

## 2. Phase 4 Feature Completeness ✅

Every task in the Phase 4 plan is **implemented and passing**:

### Task 1 — Prompt & Service Core (`services/stories.py`) ✅
- `parse_story(raw: dict)` — strict validation: all 7 required keys, `title`/`text_en`/`retell_prompt`/`target_chunk` non-empty strings, `glossary` non-empty list with `en`+`ru` keys, exactly **2** comprehension questions each with `q`/`options`(len 2)/`answer`/`hint_ru`. ✅
- `format_story(story)` — markdown title, bold glossary header, question 1/2 block. ✅
- `generate_story_async(conn, llm, level, topic, student_id)` — async via `asyncio.to_thread`-wrapped Groq call. ✅
- Prompt template `STORY_SYSTEM_PROMPT` + `build_story_user_prompt` in `llm/prompts.py`. ✅

### Task 2 — Smart Vocabulary Recycling ✅
- `get_recycling_words(conn, student_id, limit=3)` in `services/stories.py:84` — up to **2** due/existing `srs_cards` (ordered `due_date ASC`) + up to **1** recent `corrections.right` (`created_at DESC`). ✅
- Called in `generate_story_async` line 148; injected via `build_story_user_prompt`. ✅

### Task 3 — SQLite Storage & Cache (`db.py`) ✅
- `stories` table — `id`, `student_id` (FK nullable), `level`, `topic`, `content_json`, `created_at`. ✅
- `story_progress` table — `student_id`, `story_id` (FK), `questions_score`, `retell_transcript`, `retell_passed`, `completed_at`. ✅
- Helpers: `save_story` (returns `lastrowid`), `get_story`, `record_story_progress`. ✅

### Task 4 — Retell Evaluator ✅
- `evaluate_retell(target_chunk, transcript)` in `services/stories.py:121`:
  - Normalizes both via `services.exercises.normalize` and strips `*`.
  - **Full-chunk match**: substring check on normalized text. ✅
  - **Word-level fallback**: splits target chunk into words with `len >= 3`, checks each via `SequenceMatcher(ratio) >= 0.6` (`_words_match`). ✅ Matches the spec threshold exactly.
  - Russian feedback for pass/fail. ✅

### Task 5 — Handler FSM (`/story`) ✅
- `StorySession` StatesGroup: `answering_questions`, `waiting_retell`. ✅
- `/story` command: guards active student, checks theme length limit, checks `can_use_llm`, registers call, generates story, caches via `save_story`, sets FSM state, sends story (chunked). ✅
- `story_answer` — validates `"1"`/`"2"` input, tracks `q_idx`/`correct` in FSM data, transitions to `waiting_retell`, sends voice prompt. ✅
- `story_retell` — requires voice (rejects text with Russian prompt), checks voice duration + LLM quota, calls `save_and_transcribe`, evaluates, `record_story_progress`, batches glossary into SRS via `srs.ensure_card`, clears FSM. ✅
- Router registered in `bot.py:14`: `dp.include_router(stories.router)`. ✅

### Task 6 — Verification & Close-out ✅
- README lists `/story` in commands. ✅
- 171 tests green (6 story-unit + 5 story-flow tests). ✅

### ✅ Verdict: Phase 4 feature completeness = **100% complete and shipped.**

---

## 3. Correctness Assessment

### 3.1 Multi-User Isolation ✅ (Strong)

**Finding: `user_id` is correctly threaded through every handler → service → DB call chain.**

- `story_cmd`: `student["tg_id"]` → `generate_story_async(..., student["tg_id"])` → `save_story(conn, student["tg_id"], ...)`. ✅
- `get_recycling_words(conn, student_id)`: every query scoped with `WHERE student_id = ?`. ✅
- `record_story_progress`: `student_id` parameter in INSERT. ✅
- `srs.ensure_card(conn, student_id, ...)`: scoped to student. ✅
- `daily_usage` table uses `(student_id, day)` composite PK — per-student daily quotas. ✅

**One latent issue (data quality, not isolation):** `stories.student_id` is **nullable** (`db.py` line 85). `save_story` accepts `student_id: int | None` and the handler always passes a real `tg_id`, so NULL never occurs in practice today. A future retrieval path that doesn't filter by `student_id` could leak cross-student data. **Recommendation:** add `NOT NULL` or document NULL = "shared template" + enforce.

### 3.2 Transactions & Concurrency ⚠️ (Moderate risk — write contention)

**Finding: Connection-per-operation pattern with `conn.commit()` on every write; no explicit `BEGIN`/`ROLLBACK`; no write-ahead protection.**

- `db.py` injects a single shared `conn` via `workflow_data` (`bot.py:16`). ✅ Correct for async single-event-loop isolation.
- Each write method (`save_story`, `record_story_progress`, `insert_correction`, `bump_usage`, `upsert_student`, `srs.ensure_card`) calls `conn.execute` + `conn.commit()` **independently**. No multi-statement atomicity wraps the compound story-completion flow.

**The critical flow — `story_retell` (handler `stories.py:87`):**
```
1. limits.register_llm_call(conn, ...)         → bump_usage (INSERT daily_usage + COMMIT)  [line 108]
2. db.record_story_progress(...)              → INSERT story_progress + COMMIT            [lines 115-117]
3. srs.ensure_card(...) — in a loop          → INSERT OR IGNORE srs_cards + COMMIT (×N)  [lines 118-119, srs.py:14]
```

**Concrete risks:**
1. **Partial-write inconsistency:** If `record_story_progress` succeeds but a `srs.ensure_card` raises mid-loop, the story is marked complete but the glossary is only partially added to SRS. The `try/except Exception` around story *generation* (line 150) does **not** cover this completion section — an exception propagates to the global error handler which does **not** clear FSM (see §3.4).
2. **`can_use_llm`/`register_llm_call` TOCTOU race:** The check-then-increment pattern allows exceeding the daily limit under concurrent updates. **Recommendation:** use `BEGIN IMMEDIATE` or atomic increment-then-check.
3. **`check_voice` trusts client-reported `voice.duration`** (Telegram `MessageEntity`), not the downloaded audio length. Whisper billing cost-guard is **bypassable** via a spoofed duration field. **Recommendation:** validate decoded audio length post-download via `pydub`.

**What's done well:**
- `PRAGMA foreign_keys = ON` in `connect` (line 106). ✅
- FK integrity on `story_progress.story_id` → `stories(id)`. ✅
- All user-scoped queries use parameterized `?` placeholders — no SQL injection. ✅

### 3.3 Sessions & FSM Persistence ⚠️ (High impact for long-running flows)

**Finding: `MemoryStorage` is used (`bot.py:8`) — all FSM state is lost on bot restart.**

```python
dp = Dispatcher(storage=MemoryStorage())
```

- The `StorySession` FSM stores the **entire story dict** (`await state.update_data(story=story, ...)` at `handlers/stories.py:158`), the current question index, score, and `story_id`.
- **Impact:** If the bot process restarts (deployment, crash, OOM) while a learner is mid-story (between `/story` and retell submission), the story object is irrecoverably lost. There is **no fallback** to `db.get_story(story_id)` — when `data.get("story")` is None, the handler responds "История потерялась, начни заново: /story" (`story_answer` lines 53-56; `story_retell` lines 94-97).
- This affects the `/story → 2 questions → voice retell` flow (3+ state transitions), making it the **most restart-fragile** flow in the app. The lesson flow (`LessonSession.active`) is single-state and less exposed, but `/drill` and `/review` share the same property.

**Recommendation (Tier 1):** Replace `MemoryStorage` with persistence-backed storage:
- **aiogram `SQLAlchemyStorage2`/`RedisStorage2`** (preferred for multi-process), or
- A **custom SQLite-backed FSM context** storing `state`/`data` in a `fsm_state` table keyed by `user_id`.

At minimum, `story_retell` should attempt `db.get_story(conn, story_id)` as a **fallback** when `data.get("story")` is None, so progress is recoverable from the DB cache even with in-memory storage.

### 3.4 Error Handling ✅ (Robust) with one FSM gap ⚠️

**Finding: Global error handler is well-implemented; one gap in FSM cleanup.**

- `handlers/errors.py:22` — `@router.errors()` catches all unhandled exceptions, logs full traceback, **redacts `BOT_TOKEN` and `GROQ_API_KEY`** from logs (`redact` function), sends differentiated user-facing messages (LLM/groq/ratelimit/timeout vs generic). ✅
- **Critical property (per SPEC §21 item 2):** FSM state is explicitly **untouched** on error. ✅ Correct — user can retry without re-issuing `/story`.

**Gap identified:** In `story_retell`, the `try/except Exception` (line 150) catches story *generation* failures and responds with the LLM error message — but this `except` does **not** clear FSM. The user stays in the prior state. ✅ Consistent with "FSM untouched" design.

However, an **uncovered** failure path exists: if `save_and_transcribe` or `record_story_progress` or `srs.ensure_card` raises inside `story_retell` (these are **not** wrapped in try/except — only generation is), the exception propagates to the global handler, which does NOT clear FSM, leaving the user in `waiting_retell` with the story still in FSM data. The user must `/cancel` manually. This is acceptable per the retry-friendly design but **not documented**. **Recommendation:** add a narrow `try/except` around the transcription+DB-completion block that sends "Не удалось распознать речь, попробуй записать снова 🎤" while preserving FSM, distinguishing infrastructure errors from input errors.

### 3.5 Usage Limits & Quotas ✅ (Shipped and enforced)

| Limit | Constant (`services/limits.py`) | Enforced at |
|---|---|---|
| Text ≤ 1000 chars | `MAX_TEXT_CHARS = 1000` (`check_text`) | chat handler |
| Theme ≤ 80 chars | `MAX_THEME_CHARS = 80` (`check_theme`) | `/story` (line 137), lesson theme |
| Voice ≤ 120 s | `MAX_VOICE_SECONDS = 120` (`check_voice`) | `/story` retell (line 101), `/drill`, `/chat` |
| Daily LLM ≤ 200 calls | `DAILY_LLM_LIMIT = 200` (`can_use_llm`) | `/story` cmd (line 142), retell (line 105), chat, placement, lessons |

- `daily_usage` table with `(student_id, day)` PK — quota resets at midnight via key rotation. ✅
- `bump_usage` uses `INSERT ... ON CONFLICT DO UPDATE SET llm_calls = llm_calls + 1` — atomic increment. ✅
- Both generation and transcription count as LLM calls (2 per `/story` cycle). ✅

---

## 4. Test Coverage Analysis

**Total: 171 tests, all green, ruff clean.** Breakdown relevant to Phase 4 and correctness:

| Test file | Tests | Coverage |
|---|---|---|
| `tests/test_stories.py` | 6 | `parse_story` (valid, missing field, invalid q-count), `format_story`, `get_recycling_words` (empty + cards+corrections), `evaluate_retell` (success + missing chunk) |
| `tests/test_stories_flow.py` | 5 | `story_cmd` (requires active student, starts questions, saves story), full `story_answer` → `story_retell` flow (2/2 score, SRS card created), wrong answer continues, retell rejects text |
| `tests/test_db.py` | 6 | `save_story`, `record_story_progress`, upsert, etc. |
| `tests/test_srs.py` | 5 | `ensure_card` (creates once), `answer` ladder, due cards, missing card |
| `tests/test_limits.py` | 9 | quota enforcement, `check_text`, `check_voice`, `check_theme` |
| `tests/test_hardening_flows.py` | 7 | `/cancel` from registration+lessons, long lesson chunking, numbering 1-4, config validation, **K2 deferred assertion** |
| `tests/test_bot_wiring.py` | 2 | router registration, workflow_data |
| **Other** | ~132 | placement, lessons, review, chat, admin, config, scheduler, stats, invites |

### ✅ Well-tested
- Story parsing/validation, recycling word fetch, retell evaluation logic.
- End-to-end story flow with `FakeLLM` + `monkeypatch` of transcription.
- Usage limits per-call enforcement.

### ⚠️ Coverage gaps (correctness dimensions)

| Gap | Severity | Details |
|---|---|---|
| **Concurrent write safety** | High | No test exercises `story_retell` write sequence under concurrency. The `can_use_llm`/`register_llm_call` TOCTOU race is untested. |
| **Session restart recovery** | High | No test simulates bot restart (clearing `MemoryStorage`) and verifies story recovery from `db.get_story`. The "История потерялась" path is untested. |
| **Cross-user data isolation** | Medium | No test runs two students through `/story` concurrently and asserts stories/progress/SRS never interleave. Tests use fixed `tg_id=42`. |
| **`retell_transcript` NULL handling** | Low | Column allows NULL; no test for Whisper returning empty. (Handler does guard `if not transcript.strip()` → Russian re-prompt, but DB NULL path untested.) |
| **Whisper transcription failure** | Low | `save_and_transcribe` raises `VoiceTranscribeError`; no test asserts handler surfaces friendly message + preserves FSM. |
| **Story generation LLM failure** | Low | The `except Exception` around `generate_story_async` (line 150) returns "Проблема с сервисом историй" — but no test confirms this fires when LLM raises. |

### ⚠️ Test quality issue
Several tests in `test_stories_flow.py` use `FakeLLM` returning a **hardcoded valid story** (`RAW` dict) rather than exercising the real prompt → `parse_story` boundary. The unit tests in `test_stories.py` cover `parse_story` directly, but the **integration** of LLM-output → `parse_story` → handler has a coverage gap.

---

## 5. Risk Summary

| # | Finding | Severity | Status | Recommendation |
|---|---|---|---|---|
| 1 | `MemoryStorage` — FSM lost on restart; `/story` progress irrecoverable | **High** | Open | Switch to SQLAlchemy/Redis-backed FSM storage; add `db.get_story` fallback |
| 2 | No transaction wrapping the `story_retell` write sequence (3 + N writes) | **High** | Open | Wrap completion flow in `with conn:` + `try/except` with rollback |
| 3 | `can_use_llm`/`register_llm_call` TOCTOU race on daily quota | **Medium** | Open | Use `BEGIN IMMEDIATE` or atomic increment+check |
| 4 | `stories.student_id` nullable — no uniqueness on shared stories | **Low** | Open | Add `NOT NULL` or explicit "template" flag + uniqueness |
| 5 | `voice.duration` trusted from client (Whisper cost-guard bypassable) | **Low** | Open | Validate audio length post-download via `pydub` |
| 6 | Documentation drift: SPEC/plan reference non-existent module paths | **Low** | Open | Update plan file paths or add alias modules |
| 7 | Docker exists on disk but SPEC says "Phase 4"; no CI workflow | **Low** | Shipped (partial) | Add GitHub Actions: test + ruff + (optional) docker build |
| 8 | Uncovered failure paths in story handler (transcription failure, LLM error) | **Low** | Open | Add tests for these branches |

---

## 6. Verdict

**Phase 4 is functionally complete and deployed-quality green.** The `/story` feature is fully wired end-to-end: command → generation with Smart Vocabulary Recycling → comprehension check (2 questions, FSM) → voice retell → Whisper transcription → `SequenceMatcher`-based chunk validation → `story_progress` recording → automatic SRS card creation from glossary. The 171-test suite, `ruff` lint, and live smoke run all pass.

**The system is correct for single-instance, low-concurrency operation.** The primary risks are **not** in Phase 4 logic but in **operational robustness**: (1) in-memory FSM means any restart mid-story loses the learner's place, and (2) the multi-write retell-completion flow has no transactional atomicity, risking partial progress/SRS writes. These are **pre-existing platform-level concerns** that Phase 4 inherits rather than introduces, but they are most visible in the story flow because it is the longest multi-state interaction.

---

*Report generated: 2026-10-22 (audit environment: Python 3.13, aiogram 3.x, sqlite3 stdlib). No code was modified during this audit.*
