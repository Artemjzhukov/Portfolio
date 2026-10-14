"""Тесты эндпоинтов дашборда: токены, сборка HTML, авторизация, материалы."""

from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app


def _bind(settings, monkeypatch, store):
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "_get_job_store", lambda db_path: store)
    return TestClient(app)


class TestDashboardEndpoint:
    def test_valid_token_renders_blocks(self, settings, tmp_path, monkeypatch, caplog):
        from app.jobs import JobStore
        from app.schemas import EvaluationRecord, TaskBreakdown

        store = JobStore(str(tmp_path / "jobs.db"))
        store.save_result(EvaluationRecord(
            job_id="j1", student_id="s1", subject_id="history", submission_type="standard_test",
            test_title="T j1", total_score=3, max_possible_score=4, percentage=0,
            task_breakdown=[TaskBreakdown(
                task_number=1, max_points=1, earned_points=0, status="Incorrect",
                student_answer="x", correct_answer_or_criteria="y",
                deduction_reason="Перепутал дату", recommended_topics="Отмена крепостного права",
            )],
            evaluated_at=100.0,
        ))
        raw = store.issue_token("s1", "42", now=100.0)
        client = _bind(settings, monkeypatch, store)
        resp = client.post("/dashboard/token", json={"student_id": "s1", "telegram_chat_id": "42"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["student_id"] == "s1"
        assert body["chat_id"] == "42"
        link = body["dashboard_url"]
        assert "/dashboard/s1?token=" in link

        token = link.rsplit("token=", 1)[1]
        page = client.get("/dashboard/s1", params={"token": token})
        assert page.status_code == 200
        html = page.text
        assert "3.0" in html and "75" in html
        assert "Перепутал дату" in html
        assert "Отмена крепостного права" in html
        assert "T j1" in html


    def test_token_issued_for_demo_student(self, settings, tmp_path, monkeypatch):
        from app.jobs import JobStore

        store = JobStore(str(tmp_path / "jobs.db"))
        client = _bind(settings, monkeypatch, store)
        resp = client.post("/dashboard/token", json={"student_id": "demo", "telegram_chat_id": "1"})
        assert resp.status_code == 200
        assert "/dashboard/demo?token=" in resp.json()["dashboard_url"]

    def test_reissue_revokes_previous(self, settings, tmp_path, monkeypatch):
        from app.jobs import JobStore

        store = JobStore(str(tmp_path / "jobs.db"))
        client = _bind(settings, monkeypatch, store)
        first = client.post("/dashboard/token", json={"student_id": "s1", "telegram_chat_id": "42"})
        second = client.post("/dashboard/token", json={"student_id": "s1", "telegram_chat_id": "42"})
        old_token = first.json()["dashboard_url"].rsplit("token=", 1)[1]
        assert client.get("/dashboard/s1", params={"token": old_token}).status_code == 403
        new_token = second.json()["dashboard_url"].rsplit("token=", 1)[1]
        assert client.get("/dashboard/s1", params={"token": new_token}).status_code == 200

    def test_wrong_chat_rejected(self, settings, tmp_path, monkeypatch):
        from app.jobs import JobStore

        store = JobStore(str(tmp_path / "jobs.db"))
        client = _bind(settings, monkeypatch, store)
        other = store.issue_token("s1", "43", now=100.0)
        resp = client.get("/dashboard/s1", params={"token": other})
        assert resp.status_code == 403

    def test_unknown_token_rejected(self, settings, tmp_path, monkeypatch):
        from app.jobs import JobStore

        store = JobStore(str(tmp_path / "jobs.db"))
        client = _bind(settings, monkeypatch, store)
        resp = client.get("/dashboard/s1", params={"token": "x" * 32})
        assert resp.status_code == 403

    def test_token_is_single_use(self, settings, tmp_path, monkeypatch):
        from app.jobs import JobStore

        store = JobStore(str(tmp_path / "jobs.db"))
        client = _bind(settings, monkeypatch, store)
        raw = store.issue_token("s1", "42")
        assert client.get("/dashboard/s1", params={"token": raw}).status_code == 200
        assert client.get("/dashboard/s1", params={"token": raw}).status_code == 403

    def test_empty_dashboard_renders(self, settings, tmp_path, monkeypatch):
        from app.jobs import JobStore

        store = JobStore(str(tmp_path / "jobs.db"))
        client = _bind(settings, monkeypatch, store)
        raw = store.issue_token("newbie", "7")
        resp = client.get("/dashboard/newbie", params={"token": raw})
        assert resp.status_code == 200
        assert "пока нет проверенных работ" in resp.text
