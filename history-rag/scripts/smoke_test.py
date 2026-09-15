# -*- coding: utf-8 -*-
"""Смоук-тест: реальный запрос к запущенному uvicorn без вмешательства LLM."""
import base64
import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

text = "Фамилия: Петров\n№1 3\n№2 7\n№3 Александр Второй"
payload = {
    "file_bytes": base64.b64encode(text.encode("utf-8")).decode(),
    "file_name": "work.txt",
    "submission_type": "standard_test",
    "subject_id": "history",
    "student_id": "tg_12345",
    "answer_key": {"1": "3", "2": "5", "3": "Александр Второй"},
}
req = urllib.request.Request(
    "http://localhost:8000/process-submission",
    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    headers={"Content-Type": "application/json; charset=utf-8"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=30) as resp:
    result = json.loads(resp.read().decode("utf-8"))

print("percentage:", result["percentage"])
print("total:", result["total_score"], "/", result["max_possible_score"])
for t in result["task_breakdown"]:
    print(f"№{t['task_number']}: {t['status']} ({t['earned_points']}/{t['max_points']})")
print("warnings:", result["warnings"])
print("--- summary_feedback ---")
print(result["summary_feedback"])
