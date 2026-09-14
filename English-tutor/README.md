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

Или одной командой на Windows: `powershell -File run.ps1`

### Работа на своей машине

- База (`tutor.db`) и `.env` лежат в папке проекта — не коммитятся.
- Логи идут в консоль (INFO); полные трейбecs ошибок видно там же.
- Бот работает, пока открыт терминал; остановка — `Ctrl+C`.
- Docker — отложено (Phase 4), сейчас запуск только локально через uv.

## Команды

- Админ: `/invite`, `/approve <tg_id> [A2|B1|B2]`, `/students`
- Студент: `/start` (код приглашения → тест), `/lessons` (уроки + свободные темы),
  `/drill` (задание на говорение), `/review` (повторение слов), `/chat` (разговор с исправлениями),
  `/mylevel` (твой уровень и прогресс), `/cancel` (выйти из любого режима)
- Админ также: `/stats` (обзор всех), `/stats <tg_id>` (детально: слабые места, точность, неделя)
- Напоминания приходят автоматически в `REMINDER_TIMES` (по умолчанию 13:00 и 19:00, TZ из .env),
  недельный отчёт админу — `WEEKLY_SUMMARY_DAY/TIME` (по умолчанию воскресенье 19:00)

## Качество

```bash
uv run pytest -v          # 135 tests
uv run ruff check .       # lint
```
