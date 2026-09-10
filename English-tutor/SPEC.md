# English Tutor Bot — Product Specification

> **Stage 1 output (Grill)** — per `.clinerules`. Status: **✅ Approved** («Plan is Approved»).
> **Development status:** Phase 1 MVP **complete** — 85 tests green, live smoke test passed (2026-09-09). Phase 2 next (see §20–21).
> Decisions locked during interview with the owner (12 questions, one branch at a time).

## 1. What we're building
A Telegram bot that tutors English for Russian speakers. It teaches grammar (B), runs corrected conversation practice (C), and is **voice-first**: learners speak as much as possible — every exercise and chat message can be a voice message, transcribed by Groq Whisper. A vocabulary SRS (Anki-style) grows automatically from each learner's own mistakes.

**Audience:** 2–4 invited learners, manually approved by the owner. Target levels **A2–B2** (A1 and C1/C2 explicitly out of scope).

## 2. Users & Roles
| Role | Who | Powers |
|---|---|---|
| Admin | The owner (single, `ADMIN_TELEGRAM_ID`) | Generate invite codes, approve learners + confirm level, view students & stats |
| Learner | Invited friends | Placement test → lessons → drills → chat → reviews |

## 3. Access & Onboarding
1. Admin creates invite codes: `/invite` → `TUTOR-XXXX`.
2. Without a valid code the bot only says: «Доступ по приглашению. Введите код:»
3. With a code: learner sends name → takes placement test → status **pending**.
4. Admin gets a notification with test results (written score + voice transcript + suggested level) and approves: `/approve <id> [level]` (admin can override the suggested level).
5. Approved learner unlocks everything.

## 4. Placement Test (locked: variant B)
- 15–20 multiple-choice grammar/vocab questions, difficulty ascending (A2→B2).
- One voice answer: «Расскажи о своём дне» → Groq Whisper transcription → baseline production sample.
- Bot computes a **suggested** level (A2/B1/B2); **admin confirms or adjusts** at approval. Nothing is auto-final.

## 5. Grammar Lessons (locked: hybrid content)
- Hardcoded **curriculum spine**: ~4–6 topics per level (A2, B1, B2) — titles, goals (RU), grammar points. Drafted in Stage 2, owner-editable.
- On first use of a topic, the LLM generates: explanation in Russian + 3–5 exercises (fill-in / translate RU→EN) + final voice task. **Cached in SQLite** so all learners get stable, reviewable content.
- Learner answers inline; bot checks; voice answers are allowed (transcribed → same checker).

## 6. Free-form Theme Lessons (locked)
- Learner can type any theme («готовка», «собеседование», «путешествия»).
- Bot generates a custom lesson at the learner's level: grammar from the curriculum, vocabulary/texts/examples around the theme. Cached per student. New words feed the SRS.

## 7. Conversation Practice (locked: natural reply + corrections)
- Free chat; bot offers 2–3 suggested topics (from level/learner's themes) but any topic is allowed.
- Each learner message (text or voice→transcript) = **one Groq call** returning strict JSON:
  `{"reply": "...", "corrections": [{"wrong": "...", "right": "...", "hint_ru": "..."}]}`
- Bot sends: natural English reply + block «📝 Исправления:» with brief Russian hints.
- Corrections are stored (future stats) and auto-added to the learner's SRS deck.

## 8. Voice (locked: transcription only)
- **Voice in everywhere, text out.** Learners can answer any exercise or chat message by voice.
- Pipeline: Telegram voice → Groq `whisper-large-v3` → text → same logic as typed text.
- **No pronunciation scoring, no TTS in v1.**

## 9. Speaking Drills
- Standalone mode `/drill`: bot sends a phrase or free-speaking prompt («Опиши свой день в 3 предложениях») → learner responds by voice → transcription → grammar feedback + comprehension check.
- A voice task closes every lesson.

## 10. Vocabulary SRS (locked: personal, auto-collected)
- Words come from the learner's own life: corrections from chat + new lesson vocabulary (manual admin word-sets optional later).
- Interval ladder: **1д → 3д → 7д → 14д → 30д**; a fail resets the word to 1д.
- Review format: RU→EN / EN→RU.
- Delivery: pushed with daily reminders **and** on demand via `/review`.

## 11. Reminders (locked: fixed times)
- 1–2× per day at fixed config times (default **13:00 & 19:00**, Kyiv time).
- Reminder = motivational nudge + due SRS portion (5–10 words) + lesson suggestion.

## 12. Tech Stack (locked)
- **Python 3.12+** · **aiogram 3.x** · **groq** (official client)
- **SQLite** via stdlib `sqlite3` — no ORM, no external DB.
- Config in `.env`: `BOT_TOKEN`, `GROQ_API_KEY`, `ADMIN_TELEGRAM_ID`, `REMINDER_TIMES`, `TZ`.
- Run: long-lived process via `uv run`; **no Docker in v1**.
- Models (configurable): `whisper-large-v3` (voice), `openai/gpt-oss-120b` (all text LLM tasks; updated from the original `llama-3.3-70b-versatile` after the live Groq model check on 2026-09-09). One provider — Groq for everything.

## 13. Data Model (SQLite, draft)
- `students(tg_id, name, level, status, created_at)`
- `invite_codes(code, used_by, created_at)`
- `test_results(student_id, written_score, voice_transcript, suggested_level)`
- `lessons(id, kind[curriculum|theme], level, topic, student_id?, content_json, created_at)`
- `lesson_progress(student_id, lesson_id, status, score)`
- `corrections(id, student_id, wrong, right, hint_ru, source, created_at)`
- `srs_cards(id, student_id, word_en, word_ru, interval_index, due_date)`

## 14. Commands
**Learner:** `/start` (invite flow) · `/lessons` (menu + themes) · `/drill` · `/review` · `/mylevel`
**Admin:** `/invite` · `/approve <id> [level]` · `/students` · `/stats <id>`

## 15. Build Phases (locked)
- **Phase 1 (MVP):** skeleton + config + DB → invite/approval → placement test → lessons (menu + free themes, cached content, voice-in answers) → `/drill`.
- **Phase 2:** conversation corrections (JSON) → SRS + auto-collection → reminders.
- **Phase 3:** `/stats`, error-pattern tracking, weekly summaries.

## 16. Testing (per workspace rules)
- TDD with **pytest** (`uv run pytest`) before implementing core logic: SRS ladder, exercise checking, level assignment, invite flow, JSON-correction parsing.
- Telegram & Groq are mocked in tests; a real-token smoke test is run manually.

## 17. Explicit Non-Goals (v1)
Pronunciation scoring (phoneme-level) · TTS · SM-2 algorithm · multi-admin · payments · web dashboard · Docker · A1/C1/C2 levels · auto-approval.

## 18. Open Questions (to settle later)
- Exact reminder times & timezone handling (DST).
- Which Groq chat model is live at build time (llama-3.3-70b vs newer).
- Whether manual admin word-sets are needed in Phase 2 or deferred.

## 19. Decision Log
| # | Decision | Source |
|---|---|---|
| 1 | Scope: grammar + conversation + voice transcription | Q1 |
| 2 | Placement: MC test + 1 voice answer; bot suggests, admin confirms | Q2 |
| 3 | Content: curated spine + LLM-generated, cached; Groq for everything | Q3 |
| 4 | Chat: natural reply + structured JSON corrections | Q4 |
| 5 | Voice: transcription only, no pronunciation scoring | Q5 |
| 6 | Stack: aiogram 3 + groq + sqlite3 + uv run | Q6 |
| 7 | Access: invite codes; single admin | Q7 |
| 8 | Curriculum spine ~4–6 topics/level (drafted in Stage 2); reminders 2×/day | Q8 |
| 9 | Voice-in everywhere + standalone drill; text out; fixed reminder times | Q9 |
| 10 | SRS: auto-collected personal decks; 1/3/7/14/30 ladder; push + `/review` | Q10 |
| 11 | Free-form theme lessons; chat suggests topics | Q11 |
| 12 | Phases 1→2→3 as above; TDD with pytest | Q12 |

## 20. Post-MVP Hardening Log (Phase 1 review fixes — all shipped & tested)

**Access control**
- Admin commands (`/invite`, `/approve`, `/students`) verify sender == `ADMIN_TELEGRAM_ID`; others get «Эта команда только для админа.» (was: open to anyone).

**Placement (critical bugs fixed)**
- `suggest_level` covers the full 0–20 range: **A2: 0–11, B1: 12–16, B2: 17–20** (was: scores 0–5 crashed with `StopIteration`).
- `voice_hint` follows a strict rule: moves the result **one band only**, and **only when the written score is within 1 point of the boundary** toward the hinted band (e.g. 11+B1→B1, 12+A2→A2, 5+B1→A2, 10+B2→A2). Explicit boundary tests cover 11/12/13/16/10 cases.

**Invite codes (contract fixed)**
- `redeem` returns `True` only if the code exists, is unused, **and the student's status is `new`/missing** — an `active`/`pending`/`blocked` student can no longer redeem a code and reset their own status.
- Atomic claim: `UPDATE invite_codes SET used_by=? WHERE code=? AND used_by IS NULL` (single-winner guarantee; on lost race the student-status change is rolled back).

**Conversation robustness (live crashes fixed)**
- Voice answers during lesson **exercises**: voice → duration/limit checks → Whisper → transcript checked as the answer (spec §8 honored).
- Stickers/photos/other media at any step → polite re-prompt («Ответь текстом или голосом 🎤»), no `NoneType` crashes; `normalize(None)` is safe.
- Text during `/drill` → explicit «Здесь я жду голосовое сообщение 🎤 …»; text at the final voice step → explicit prompt; voice during the 20 MC questions → «ответь числом 0–3, голосовые — в конце теста 🎤».
- Voice message instead of invite code or name → re-prompt, no crash.
- `upsert_student` sets `level` on **insert** too (was: only on update → students would have `level=NULL`).

**Cost guards (shipped)**
- Text ≤1000 chars, themes ≤80 chars, voice ≤120 s — all rejected **before** any LLM/ASR call.
- Daily LLM quota: 200 calls/student/day, counted per call in SQLite (`daily_usage`), resets at midnight. All limits are constants in `services/limits.py`.

**Lesson validation & LLM reality**
- `parse_lesson` is strictly typed: non-empty strings for title/explanation/voice_task, exercises 3–5 with validated types and non-empty fields, vocab 8–12 with exact `en`/`ru` string fields (was: presence-only checks).
- Live Groq model check on 2026-09-09: default text model is **`openai/gpt-oss-120b`** (`llama-3.3-70b-versatile` no longer exists); `whisper-large-v3` confirmed available.

## 21. Open Items (known gaps → Phase 2 backlog)
1. **Blocking LLM/ASR calls** — `GroqService` is synchronous; wrap in `asyncio.to_thread` (or `AsyncGroq`) to avoid stalling the event loop under concurrent learners.
2. **Central error handler** — `@router.errors()`: user gets «временная проблема», full traceback goes to log (currently unhandled errors only print to console).
3. **`/cancel`** — explicit exit from test/lesson/drill with FSM reset (currently only `/start` resets).
4. **Message splitting** — `format_lesson` output >4096 chars would fail Telegram's limit; split into parts.
5. **SQLite integrity** — `CHECK` constraints on `status`/`level`, partial unique indexes for lessons (NULL in UNIQUE), `ON DELETE` policy, retry on invite-code collision.
6. **Env validation** — validate `ADMIN_TELEGRAM_ID` (integer), warn on empty; mark `REMINDER_TIMES`/`TZ` as Phase 2.
7. **`ruff`** linter + CI step.
8. Phase 2 features proper (SPEC §15): chat corrections JSON (with `can_use_llm` wired from day one), SRS deck + auto-collection, reminders at 13:00/19:00.

**Testing state:** 85 tests green (`uv run pytest`); Phase 1 live smoke test passed by owner on own account (both roles).
