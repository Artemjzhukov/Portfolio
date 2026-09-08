# English Tutor Bot — Product Specification

> **Stage 1 output (Grill)** — per `.clinerules`. Status: **awaiting user approval** to move to Stage 2 (Curriculum Planner).
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
- Models (configurable): `whisper-large-v3` (voice), `llama-3.3-70b-versatile` (all text LLM tasks). One provider — Groq for everything.

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
