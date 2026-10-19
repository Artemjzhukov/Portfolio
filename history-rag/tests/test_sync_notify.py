"""Тесты фазы 8: Telegram-текст результата, Notion-пейлоад, фоновый неблокирующий синк."""

from __future__ import annotations


def _record(**overrides):
    from app.schemas import EvaluationRecord

    base = {
        "job_id": "j8",
        "student_id": "Иван (тг 42)",
        "subject_id": "history",
        "submission_type": "standard_test",
        "test_title": "history · 2025-10-26",
        "total_score": 3.0,
        "max_possible_score": 4.0,
        "percentage": 75.0,
        "task_breakdown": [
            {
                "task_number": 1, "max_points": 2, "earned_points": 2,
                "status": "Correct", "student_answer": "3",
                "correct_answer_or_criteria": "3",
                "deduction_reason": "", "recommended_topics": "",
            },
            {
                "task_number": 2, "max_points": 2, "earned_points": 1,
                "status": "Partially Correct", "student_answer": "7",
                "correct_answer_or_criteria": "5",
                "deduction_reason": "Правильный ответ: 5. В работе: 7",
                "recommended_topics": "Отмена крепостного права",
            },
        ],
        "needs_human_review": False,
        "evaluated_at": 1761446400.0,
    }
    base.update(overrides)
    return EvaluationRecord(**base)


class TestResultTelegramText:
    def test_text_matches_spec_format(self):
        from app.services.notify import build_result_message

        msg = build_result_message(
            _record(), chat_id="42", dashboard_url="https://app.example/dashboard/x",
        )
        assert msg.chat_id == "42"
        assert msg.parse_mode == "HTML"
        assert "Вариант проверен!" in msg.text_ru
        assert "3 из 4 (75%)" in msg.text_ru
        assert "https://app.example/dashboard/x" not in msg.text_ru
        assert msg.dashboard_url == "https://app.example/dashboard/x"

    def test_html_in_student_text_is_escaped(self):
        from app.services.notify import build_result_message

        rec = _record(task_breakdown=[{
            "task_number": 1, "max_points": 1, "earned_points": 0,
            "status": "Incorrect", "student_answer": "<b>x</b>",
            "correct_answer_or_criteria": "y",
            "deduction_reason": "В работе: <script>alert(1)</script>",
            "recommended_topics": "",
        }])
        msg = build_result_message(rec, chat_id="42", dashboard_url="https://app.example/d")
        assert "<script>" not in msg.text_ru
        assert "&lt;script&gt;" in msg.text_ru

    def test_long_reasons_stay_within_4096(self):
        from app.services.notify import build_result_message

        rec = _record(task_breakdown=[{
            "task_number": i, "max_points": 1, "earned_points": 0,
            "status": "Incorrect", "student_answer": "x",
            "correct_answer_or_criteria": "y",
            "deduction_reason": "ошибка " * 500,
            "recommended_topics": "",
        } for i in range(20)])
        msg = build_result_message(rec, chat_id="42", dashboard_url="https://app.example/d")
        assert len(msg.text_ru) <= 4096

    def test_review_flag_mentioned(self):
        from app.services.notify import build_result_message

        msg = build_result_message(
            _record(needs_human_review=True),
            chat_id="42", dashboard_url="https://app.example/d",
        )
        assert "ручной проверки" in msg.text_ru


class TestNotionPayload:
    def test_from_record_keeps_notion_fields(self):
        from app.services.notify import build_notion_payload

        payload = build_notion_payload(
            _record(), student_name="Иван Петров",
            dashboard_url="https://app.example/dashboard/x",
        )
        assert payload.student_name == "Иван Петров"
        assert payload.test_title == "history · 2025-10-26"
        assert payload.score == 3.0
        assert payload.percentage == 75.0
        assert payload.dashboard_url == "https://app.example/dashboard/x"
        assert payload.job_id == "j8"
        assert payload.needs_human_review is False
        # ISO-дата
        from datetime import datetime

        datetime.fromisoformat(payload.date.replace("Z", "+00:00"))


class TestBackgroundSync:
    def test_send_is_nonblocking_and_never_raises(self):
        import time

        from app.services.notify import schedule_result_sync

        calls = []

        def slow_post(url, payload):
            import time as _t

            _t.sleep(0.05)
            calls.append((url, payload))
            return True

        started = time.monotonic()
        schedule_result_sync(
            _record(), sender=slow_post,
            notion_url="https://notion.example/pages",
            telegram_url="https://telegram.example/send",
            notify=None,
        )
        elapsed = time.monotonic() - started
        assert elapsed < 0.05, "синк должен возвращаться сразу, без блокировки"
        # фоновая отправка всё же состоялась (ждём оба вызова)
        deadline = time.monotonic() + 2.0
        while len(calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(calls) == 2

    def test_sender_errors_are_swallowed(self):
        from app.services.notify import schedule_result_sync

        def boom(url, payload):
            raise RuntimeError("сеть упала")

        notified = []
        # без URL каналов — вызов должен сразу завершиться без задач на отправку
        schedule_result_sync(_record(), sender=boom, notify=notified.append)
        # ...и асинхронно тоже
        import time as _t

        _t.sleep(0.3)
        assert notified == []

    def test_distinct_urls_per_channel(self):
        import time as _t

        from app.services.notify import schedule_result_sync

        calls = {}

        def router(url, payload):
            calls[url] = payload

        schedule_result_sync(
            _record(),
            sender=router,
            notion_url="https://notion.example/pages",
            telegram_url="https://telegram.example/send",
            notion_dashboard_url="https://app.example/dashboard/s1?token=TEACHER",
            telegram_dashboard_url="https://app.example/dashboard/s1?token=STUDENT",
        )
        deadline = _t.monotonic() + 2.0
        while len(calls) < 2 and _t.monotonic() < deadline:
            _t.sleep(0.01)
        assert calls["https://notion.example/pages"]["dashboard_url"].endswith("token=TEACHER")
        assert calls["https://telegram.example/send"]["dashboard_url"].endswith("token=STUDENT")

    def test_partial_config_sends_only_configured_channel(self):
        import time as _t

        from app.services.notify import schedule_result_sync

        calls = []
        schedule_result_sync(
            _record(), sender=lambda url, payload: calls.append((url, payload)),
            notion_url="https://notion.example/pages",
            telegram_url=None,
        )
        deadline = _t.monotonic() + 2.0
        while len(calls) < 1 and _t.monotonic() < deadline:
            _t.sleep(0.01)
        assert len(calls) == 1
        assert calls[0][0] == "https://notion.example/pages"

    def test_legacy_single_dashboard_url_still_works(self):
        """Старый общий dashboard_url — фолбэк для обоих каналов (обратная совместимость)."""
        import time as _t

        from app.services.notify import schedule_result_sync

        calls = {}

        def router(url, payload):
            calls[url] = payload

        schedule_result_sync(
            _record(), sender=router,
            notion_url="https://notion.example/pages",
            telegram_url="https://telegram.example/send",
            dashboard_url="https://app.example/dashboard/s1?token=SHARED",
        )
        deadline = _t.monotonic() + 2.0
        while len(calls) < 2 and _t.monotonic() < deadline:
            _t.sleep(0.01)
        assert calls["https://notion.example/pages"]["dashboard_url"].endswith("token=SHARED")
        assert calls["https://telegram.example/send"]["dashboard_url"].endswith("token=SHARED")
        import time as _t

        from app.services.notify import schedule_result_sync

        calls = []
        schedule_result_sync(
            _record(), sender=lambda url, payload: calls.append((url, payload)),
            notion_url="https://notion.example/pages",
            telegram_url=None,
        )
        deadline = _t.monotonic() + 2.0
        while len(calls) < 1 and _t.monotonic() < deadline:
            _t.sleep(0.01)
        assert len(calls) == 1
        assert calls[0][0] == "https://notion.example/pages"

    def test_broken_sender_reports_but_never_raises(self):
        import time as _t

        from app.services.notify import schedule_result_sync

        def boom(url, payload):
            raise RuntimeError("сеть упала")

        notified = []
        # не должно кидать исключение синхронно...
        schedule_result_sync(
            _record(), sender=boom,
            notion_url="https://notion.example/pages",
            telegram_url="https://telegram.example/send",
            notify=notified.append,
        )
        # ...и асинхронно тоже
        import time as _t

        _t.sleep(0.3)
        assert notified and "сеть упала" in notified[0]


class TestSubmissionNotifyFields:
    def test_optional_fields_default_none(self):
        from app.schemas import SubmissionInput

        payload = SubmissionInput(
            file_url="https://example.com/w.jpg",
            submission_type="standard_test",
            subject_id="history",
            student_id="s1",
        )
        assert payload.telegram_chat_id is None
        assert payload.student_name is None

    def test_chat_id_with_space_rejected(self):
        import pytest

        from app.schemas import SubmissionInput

        with pytest.raises(Exception):
            SubmissionInput(
                file_url="https://example.com/w.jpg",
                submission_type="standard_test",
                subject_id="history",
                student_id="s1",
                telegram_chat_id="12 34",
            )

    def test_fields_survive_payload_dump(self):
        from app.schemas import SubmissionInput

        payload = SubmissionInput(
            file_url="https://example.com/w.jpg",
            submission_type="standard_test",
            subject_id="history",
            student_id="s1",
            telegram_chat_id="42",
            student_name="Иван",
        )
        dumped = payload.model_dump()
        assert dumped["telegram_chat_id"] == "42"
        assert dumped["student_name"] == "Иван"


class TestRunJobQuietSkip:
    def test_no_webhooks_configured_schedules_nothing(self, tmp_path, monkeypatch):
        """Без вебхуков синк не планируется (тихий пропуск), результат сохраняется."""
        import app.main as main_module
        from app.jobs import JobStore
        from app.schemas import AssessmentResult

        store = JobStore(str(tmp_path / "jobs.db"))
        store.create(
            "j-quiet", student_id="s1",
            subject_id="history", submission_type="standard_test",
            file_hash="ab",
        )
        result = AssessmentResult(
            student_id="s1", subject_id="history",
            submission_type="standard_test",
            total_score=1.0, max_possible_score=2.0, percentage=50.0,
            summary_feedback="ok", task_breakdown=[],
        )

        class _Pipeline:
            def run(self, payload, file_bytes, file_name, job_id=None):
                return result

        called = []
        monkeypatch.setattr(
            "app.services.notify.schedule_result_sync",
            lambda *a, **k: called.append(k),
        )
        settings = main_module.get_settings()
        monkeypatch.setattr(settings, "notion_webhook_url", "")
        monkeypatch.setattr(settings, "telegram_webhook_url", "")

        main_module._run_job(
            store, _Pipeline(), "j-quiet",
            {
                "file_url": "https://example.com/w.jpg",
                "submission_type": "standard_test",
                "subject_id": "history",
                "student_id": "s1",
            },
            b"bytes", "w.jpg",
            settings=settings,
        )
        assert called == []
        assert store.get_result_record("j-quiet") is not None
