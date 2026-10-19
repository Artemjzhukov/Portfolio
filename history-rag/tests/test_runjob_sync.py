"""Интеграция _run_job -> фоновый синк Notion/Telegram (джоба done -> ссылки -> вебхуки)."""


class TestRunJobSchedulesSync:
    def test_done_job_schedules_notion_and_telegram(self, tmp_path, monkeypatch):
        """После set_done планируется синк: токен дашборда -> ссылки -> оба вебхука."""
        import app.main as main_module
        from app.jobs import JobStore
        from app.schemas import AssessmentResult

        store = JobStore(str(tmp_path / "jobs.db"))
        store.create(
            "j-sync", student_id="Иван",
            subject_id="history", submission_type="standard_test",
            file_hash="ab",
        )
        result = AssessmentResult(
            student_id="Иван", subject_id="history",
            submission_type="standard_test",
            total_score=3.0, max_possible_score=4.0, percentage=75.0,
            summary_feedback="ok", task_breakdown=[],
        )

        class _Pipeline:
            def run(self, payload, file_bytes, file_name, job_id=None):
                return result

        captured = {}

        def fake_schedule(record, **kwargs):
            captured.update(kwargs)
            captured["job_id"] = record.job_id
            return None

        monkeypatch.setattr("app.services.notify.schedule_result_sync", fake_schedule)
        settings = main_module.get_settings()
        monkeypatch.setattr(settings, "notion_webhook_url", "https://notion.example/hook")
        monkeypatch.setattr(settings, "telegram_webhook_url", "https://tg.example/hook")
        monkeypatch.setattr(settings, "public_base_url", "https://app.example")

        main_module._run_job(
            store, _Pipeline(), "j-sync",
            {
                "file_url": "https://example.com/w.jpg",
                "submission_type": "standard_test",
                "subject_id": "history",
                "student_id": "Иван",
                "telegram_chat_id": "42",
                "student_name": "Иван Петров",
            },
            b"bytes", "w.jpg",
            settings=settings,
        )

        assert captured["notion_url"] == "https://notion.example/hook"
        assert captured["telegram_url"] == "https://tg.example/hook"
        assert captured["student_name"] == "Иван Петров"
        assert captured["chat_id"] == "42"
        assert captured["dashboard_url"].startswith("https://app.example/dashboard/")
        assert "token=" in captured["dashboard_url"]
        assert store.get_result_record("j-sync")["job_id"] == "j-sync"
