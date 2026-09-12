# English Tutor Bot

Telegram-бот-репетитор английского для русскоязычных студентов (A2–B2).
Голосовой ввод через Groq Whisper, уроки генерируются LLM и кешируются в SQLite.
Разговорная практика с исправлениями, SRS-повторение слов (Anki-style), напоминания 2 раза в день.

Документация: [`SPEC.md`](SPEC.md) (продукт), [`CURRICULUM.md`](CURRICULUM.md) (учебный план),
планы: `docs/superpowers/plans/2026-09-09-phase1-mvp.md` (Phase 1), `docs/superpowers/plans/2026-09-11-phase2.md` (Phase 2).

## Запуск

```bash
uv sync
copy .env.example .env   # fill BOT_TOKEN, GROQ_API_KEY, ADMIN_TELEGRAM_ID
uv run python -m english_tutor.main
```

## Команды

- Админ: `/invite`, `/approve <tg_id> [A2|B1|B2]`, `/students`
- Студент: `/start` (код приглашения → тест), `/lessons` (уроки + свободные темы),
  `/drill` (задание на говорение), `/review` (повторение слов), `/chat` (разговор с исправлениями),
  `/cancel` (выйти из любого режима)
- Напоминания приходят автоматически в `REMINDER_TIMES` (по умолчанию 13:00 и 19:00, TZ из .env)

## Качество

```bash
uv run pytest -v          # 135 tests
uv run ruff check .       # lint
```
