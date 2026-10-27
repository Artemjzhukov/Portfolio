# -*- coding: utf-8 -*-
"""Смоук-проверка: реальный запрос к запущенному uvicorn без вмешательства LLM.

Это НЕ pytest-тест: нужен живой сервис, поэтому он не входит в общий прогон
(см. testpaths в pytest.ini) и запускается вручную:

    uvicorn app.main:app --port 8000      # в соседнем терминале
    python scripts/smoke_test.py
    python scripts/smoke_test.py --base-url http://localhost:8010
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.request

SAMPLE_TEXT = "Фамилия: Петров\n№1 3\n№2 7\n№3 Александр Второй"
ANSWER_KEY = {"1": "3", "2": "5", "3": "Александр Второй"}


def build_payload() -> dict:
    """Тело запроса /process-submission: зачётная работа как txt в base64."""
    return {
        "file_bytes": base64.b64encode(SAMPLE_TEXT.encode("utf-8")).decode(),
        "file_name": "work.txt",
        "submission_type": "standard_test",
        "subject_id": "history",
        "student_id": "tg_12345",
        "answer_key": ANSWER_KEY,
    }


def run_smoke(base_url: str, timeout: float = 30.0) -> dict:
    """POST на /process-submission; сеть — только здесь, не при импорте."""
    url = base_url.rstrip("/") + "/process-submission"
    request = urllib.request.Request(
        url,
        data=json.dumps(build_payload(), ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def print_result(result: dict) -> None:
    print("percentage:", result["percentage"])
    print("total:", result["total_score"], "/", result["max_possible_score"])
    for task in result["task_breakdown"]:
        print(f"№{task['task_number']}: {task['status']} ({task['earned_points']}/{task['max_points']})")
    print("warnings:", result["warnings"])
    print("--- summary_feedback ---")
    print(result["summary_feedback"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Смоук-проверка /process-submission")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Адрес запущенного сервиса")
    parser.add_argument("--timeout", type=float, default=30.0, help="Таймаут запроса в секундах")
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):  # кириллица в консоли Windows
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    try:
        result = run_smoke(args.base_url, args.timeout)
    except urllib.error.URLError as exc:
        print(
            f"[smoke] сервис недоступен по {args.base_url}: {exc.reason}. "
            "Запустите uvicorn app.main:app --port 8000 и повторите.",
            file=sys.stderr,
        )
        return 1
    except (KeyError, json.JSONDecodeError) as exc:
        print(f"[smoke] неожиданный ответ сервиса: {exc!r}", file=sys.stderr)
        return 1

    print_result(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
