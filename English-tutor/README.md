# English Tutor Bot

Telegram-бот-репетитор английского для русскоязычных студентов (A2–B2).
Голосовой ввод через Groq Whisper, уроки генерируются LLM и кешируются в SQLite.

Документация: [`SPEC.md`](SPEC.md) (продукт), [`CURRICULUM.md`](CURRICULUM.md) (учебный план),
план Phase 1: `docs/superpowers/plans/2026-09-09-phase1-mvp.md`.

## Запуск

```bash
uv sync
copy .env.example .env   # fill BOT_TOKEN, GROQ_API_KEY, ADMIN_TELEGRAM_ID
uv run python -m english_tutor.main
```

## Команды

- Админ: `/invite`, `/approve <tg_id> [A2|B1|B2]`, `/students`
- Студент: `/start` (код приглашения → тест), `/lessons`, `/drill`

## Тесты

```bash
uv run pytest -v
```
