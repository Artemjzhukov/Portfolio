"""SQLite job store: асинхронная обработка, идемпотентность, аудит.

Qdrant здесь не используется сознательно: поиск джобы/эталона — это точное
совпадение по ключу, а не семантическая близость. Векторная БД для такого —
анти-паттерн; Qdrant остаётся для теории и фактчека (app/services/rag.py).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    submission_type TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT,
    error TEXT,
    created_at REAL NOT NULL,
    finished_at REAL
)
"""

# Джоба в queued/running дольше этого — считаем процесс умершим, разрешаем перезапуск.
STALE_SECONDS = 20 * 60


class JobStore:
    """Потокобезопасный стор джоб. Один файл SQLite, без внешних зависимостей."""

    def __init__(self, db_path: str) -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)

    # ------------------------------------------------------------------

    def create(
        self,
        job_id: str,
        *,
        student_id: str,
        subject_id: str,
        submission_type: str,
        file_hash: str,
    ) -> tuple[bool, Optional[dict]]:
        """Идемпотентная регистрация джобы.

        Returns:
            (reused, result_if_done):
            - новая джоба -> (False, None), строка в статусе queued;
            - уже done -> (True, результат) — n8n получает ответ мгновенно;
            - queued/running (свежая) -> (True, None) — двойной расчёт невозможен;
            - error или зависшая queued/running -> перезапуск -> (False, None).
        """
        with self._lock:
            row = self._get(job_id)
            if row is None:
                self._conn.execute(
                    "INSERT INTO jobs (job_id, student_id, subject_id, submission_type,"
                    " file_hash, status, created_at) VALUES (?, ?, ?, ?, ?, 'queued', ?)",
                    (job_id, student_id, subject_id, submission_type, file_hash, time.time()),
                )
                self._conn.commit()
                logger.info("job=%s accepted new: student=%s subject=%s type=%s",
                            job_id, student_id, subject_id, submission_type)
                return False, None
            if row["status"] == "done":
                logger.info("job=%s reuse done result (no LLM spend)", job_id)
                return True, json.loads(row["result_json"])
            if row["status"] in ("queued", "running") and time.time() - row["created_at"] <= STALE_SECONDS:
                logger.info("job=%s reuse in-flight (status=%s)", job_id, row["status"])
                return True, None
            logger.warning("job=%s reset from %s (stale or error) — re-queued", job_id, row["status"])
            self._conn.execute(
                "UPDATE jobs SET status = 'queued', error = NULL, created_at = ?,"
                " finished_at = NULL WHERE job_id = ?",
                (time.time(), job_id),
            )
            self._conn.commit()
            return False, None

    def get(self, job_id: str) -> Optional[dict]:
        with self._lock:
            row = self._get(job_id)
            return dict(row) if row else None

    def set_running(self, job_id: str) -> None:
        logger.info("job=%s running", job_id)
        self._update(job_id, "UPDATE jobs SET status = 'running' WHERE job_id = ?")

    def set_done(self, job_id: str, result: dict) -> None:
        logger.info("job=%s done", job_id)
        self._update(
            job_id,
            "UPDATE jobs SET status = 'done', result_json = ?, finished_at = ? WHERE job_id = ?",
            (json.dumps(result, ensure_ascii=False), time.time()),
        )

    def set_error(self, job_id: str, error: str) -> None:
        logger.error("job=%s error: %s", job_id, error)
        self._update(
            job_id,
            "UPDATE jobs SET status = 'error', error = ?, finished_at = ? WHERE job_id = ?",
            (error[:2000], time.time()),
        )

    # ------------------------------------------------------------------

    def _get(self, job_id: str):
        return self._conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()

    def _update(self, job_id: str, sql: str, params: tuple = ()) -> None:
        with self._lock:
            self._conn.execute(sql, (*params, job_id))
            self._conn.commit()


def compute_job_id(payload, file_bytes: bytes, settings, answer_key=None) -> str:
    """Идемпотентный ключ джобы: ученик + предмет + тип + файл + ключи + рубрики.

    answer_key — эффективный ключ (payload или хранилище); если None, берётся
    payload.answer_key. Изменение рубрик/ключей инвалидирует кэш.
    """
    effective = answer_key if answer_key is not None else (payload.answer_key or {})
    digest = hashlib.sha256()
    digest.update(f"{payload.student_id}|{payload.subject_id}|{payload.submission_type}".encode("utf-8"))
    digest.update(b"|")
    digest.update(hashlib.sha256(file_bytes).digest())
    digest.update(b"|")
    digest.update(json.dumps(effective, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    rubric_dir = Path(settings.criteria_dir) / payload.subject_id
    for path in sorted(rubric_dir.glob("task_*.json")):
        digest.update(b"|")
        digest.update(path.name.encode("utf-8"))
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()
