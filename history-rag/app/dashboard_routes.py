"""Эндпоинты дашборда: токены, сборка HTML, авторизация.

Чат НЕ входит в URL: токен идентифицирует пару (студент, чат) сам по себе,
chat_id сверяется только по записи, найденной по хэшу токена.
"""

from __future__ import annotations

import hashlib
import logging
import time
from urllib.parse import quote

from app.jobs import DASHBOARD_TOKEN_TTL_HOURS, JobStore
from app.schemas import DashboardTokenIssue
from app.services.dashboard import build_student_dashboard

logger = logging.getLogger(__name__)


def build_dashboard_url(settings, student_id: str, raw_token: str) -> str:
    """Ссылка на дашборд: {public_base_url}/dashboard/{student_id}?token=..."""
    base = (getattr(settings, "public_base_url", "") or "").rstrip("/")
    path = f"/dashboard/{quote(student_id)}?token={quote(raw_token)}"
    return f"{base}{path}" if base else path


def register_dashboard_routes(app) -> None:
    """Подключает /dashboard/* к FastAPI-приложению (вызывается из main).

    Настройки и стор резолвятся лениво через app.main на каждый запрос,
    поэтому подмена в тестах (monkeypatch) работает.
    """

    def _settings():
        from app import main as main_module

        return main_module.get_settings()

    def _store():
        from app import main as main_module

        return main_module._get_job_store(main_module.get_settings().jobs_db_path)

    @app.post("/dashboard/token")
    def issue_dashboard_token(payload: DashboardTokenIssue):
        store = _store()
        store.revoke_tokens(payload.student_id, payload.telegram_chat_id)
        raw = store.issue_token(
            payload.student_id, payload.telegram_chat_id, ttl_hours=payload.ttl_hours
        )
        url = build_dashboard_url(_settings(), payload.student_id, raw)
        logger.info("dashboard token issued via api: student=%s", payload.student_id)
        return {"student_id": payload.student_id, "chat_id": payload.telegram_chat_id, "dashboard_url": url}

    @app.get("/dashboard/{student_id}", response_class=None)
    def student_dashboard(student_id: str, token: str):
        from fastapi import HTTPException
        from fastapi.responses import HTMLResponse

        from app.schemas import DashboardAccessQuery
        from app.templates import render_dashboard

        try:
            query = DashboardAccessQuery(token=token)
        except Exception:
            raise HTTPException(status_code=403, detail="Недействительная ссылка")
        record = _consume_own_token(_store(), query.token, student_id)
        if record is None:
            raise HTTPException(status_code=403, detail="Недействительная ссылка")
        settings = _settings()
        from app.services.topic_materials import TopicMaterialsStore

        dashboard = build_student_dashboard(
            _store(), student_id,
            materials_store=TopicMaterialsStore(settings),
            media_dir=settings.media_dir,
        )
        return HTMLResponse(
            content=render_dashboard(dashboard), media_type="text/html; charset=utf-8"
        )


def _consume_own_token(store: JobStore, raw_token: str, student_id: str):
    """Хэш токена -> запись -> сверяем student_id и telegram_chat_id из БД, списываем."""
    try:
        from app.schemas import DashboardAccessQuery

        DashboardAccessQuery(token=raw_token)
    except Exception:
        return None
    token_hash = hashlib.sha256(raw_token.encode("ascii", "ignore")).hexdigest()
    with store._lock:
        row = store._conn.execute(
            "SELECT * FROM dashboard_tokens WHERE token_hash = ?", (token_hash,)
        ).fetchone()
        if row is None:
            return None
        record = dict(row)
    if record["student_id"] != student_id:
        return None
    return store.consume_token(raw_token, record["telegram_chat_id"])
