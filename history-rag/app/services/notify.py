"""Фаза 8: Telegram-текст результата, Notion-пейлоад, фоновый неблокирующий синк.

Всё на русском. Отправка никогда не блокирует API и никогда не роняет его:
ошибки сети глотаются и уходят в колбэк `notify` + лог.
"""

from __future__ import annotations

import html as _html
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_MAX_TG_LEN = 4096
_MAX_REASON = 200
_MAX_PROBLEMS = 5


def _safe_notify(notify: Callable[[str], Any], text: str) -> None:
    """Колбэк ошибок никогда не должен ронять фоновый поток."""
    try:
        notify(text)
    except Exception:  # noqa: BLE001
        pass


def _fmt_num(v: float | int) -> str:
    try:
        return f"{float(v):g}"
    except (TypeError, ValueError):
        return str(v)


def _esc(s: Any) -> str:
    return _html.escape(str(s or ""), quote=False)


def build_result_message(record, chat_id: str, dashboard_url: str):
    """Короткий ответ ученику. Ссылка на дашборд — отдельным полем, не в тексте."""
    from app.schemas import TelegramResultMessage

    total = _fmt_num(record.total_score)
    maximum = _fmt_num(record.max_possible_score)
    pct = _fmt_num(record.percentage)
    lines = [f"Вариант проверен! Ваш результат: {total} из {maximum} ({pct}%)."]
    if getattr(record, "needs_human_review", False):
        lines.append("Результат требует ручной проверки учителем.")
    problems = [t for t in (record.task_breakdown or []) if getattr(t, "status", "") != "Correct"]
    if problems:
        lines.append("Разбор:")
        for task in problems[:_MAX_PROBLEMS]:
            reason = (getattr(task, "deduction_reason", "") or "").strip()
            if len(reason) > _MAX_REASON:
                reason = reason[: _MAX_REASON - 1] + "…"
            lines.append(f"№{getattr(task, 'task_number', '?')}: {_esc(reason) if reason else '—'}")
        if len(problems) > _MAX_PROBLEMS:
            lines.append(f"…и другие ({len(problems) - _MAX_PROBLEMS}). Подробности — в дашборде.")
    text = "\n".join(lines)
    if len(text) > _MAX_TG_LEN:
        text = text[: _MAX_TG_LEN - 3] + "..."
    return TelegramResultMessage(chat_id=chat_id, text_ru=text, dashboard_url=dashboard_url)


def build_notion_payload(record, student_name: str, dashboard_url: str):
    """Строка Notion CRM учителя из записи оценки."""
    from app.schemas import NotionSyncPayload

    evaluated = float(getattr(record, "evaluated_at", 0.0) or 0.0)
    try:
        iso_date = datetime.fromtimestamp(evaluated, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        iso_date = datetime.now(tz=timezone.utc).isoformat()
    return NotionSyncPayload(
        student_name=student_name,
        test_title=record.test_title,
        score=float(record.total_score),
        percentage=float(record.percentage),
        date=iso_date,
        dashboard_url=dashboard_url,
        job_id=record.job_id,
        needs_human_review=bool(getattr(record, "needs_human_review", False)),
    )


def _default_sender(url: str, payload: Any) -> bool:
    import httpx

    response = httpx.post(str(url), json=payload if isinstance(payload, dict) else {}, timeout=10.0)
    response.raise_for_status()
    return True


def schedule_result_sync(
    record,
    sender: Optional[Callable[[str, Any], Any]] = None,
    notion_url: Optional[str] = None,
    telegram_url: Optional[str] = None,
    notify: Optional[Callable[[str], Any]] = None,
    dashboard_url: Optional[str] = None,
    notion_dashboard_url: Optional[str] = None,
    telegram_dashboard_url: Optional[str] = None,
    student_name: Optional[str] = None,
    chat_id: Optional[str] = None,
):
    """Фоновая отправка Notion + Telegram. Возвращается сразу, исключений не кидает.

    Токены дашборда одноразовые, поэтому ссылки для ученика и учителя — разные:
    `telegram_dashboard_url` (пуш ученику) и `notion_dashboard_url` (строка CRM).
    Старый `dashboard_url` остаётся как общий фолбэк для обоих.
    """
    send = sender or _default_sender

    def _work() -> None:
        job_id = getattr(record, "job_id", "unknown")
        fallback_dash = dashboard_url or f"https://example.com/dashboard/{job_id}"
        notion_dash = notion_dashboard_url or fallback_dash
        telegram_dash = telegram_dashboard_url or fallback_dash
        sname = student_name or str(getattr(record, "student_id", "ученик"))
        cid = chat_id or "0"
        targets: list[tuple[str, Any]] = []
        if notion_url:
            try:
                targets.append((notion_url, build_notion_payload(record, student_name=sname, dashboard_url=notion_dash).model_dump()))
            except Exception as exc:  # noqa: BLE001
                logger.warning("sync notion payload build failed: %s", exc)
                if notify is not None:
                    _safe_notify(notify, str(exc))
        if telegram_url:
            try:
                targets.append((telegram_url, build_result_message(record, chat_id=cid, dashboard_url=telegram_dash).model_dump()))
            except Exception as exc:  # noqa: BLE001 — напр. chat_id не похож на Telegram-ID
                logger.warning("sync telegram payload build failed: %s", exc)
                if notify is not None:
                    _safe_notify(notify, str(exc))
        for url, payload in targets:
            try:
                send(url, payload)
            except Exception as exc:  # noqa: BLE001 — глотаем, уведомляем
                logger.warning("sync to %s failed: %s", url, exc)
                if notify is not None:
                    _safe_notify(notify, f"синк {url} не удался: {exc}")

    thread = threading.Thread(target=_work, name="result-sync", daemon=True)
    thread.start()
    return thread
