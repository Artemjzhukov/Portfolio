"""Тесты Telegram-пейлоадов: HTML-экранирование и лимит 4096."""

from app.services.pipeline import TG_SHORT_LIMIT, build_telegram_short, html_escape


def result_data(**overrides):
    base = {
        "student_id": "s1",
        "subject_id": "history",
        "submission_type": "ege_exam",
        "total_score": 2.0,
        "max_possible_score": 5.0,
        "percentage": 40.0,
        "needs_human_review": False,
        "warnings": [],
        "task_breakdown": [
            {"task_number": 19, "max_points": 3, "earned_points": 2, "status": "Partially Correct",
             "deduction_reason": "K2: связь не указана", "student_answer": ""},
            {"task_number": 1, "max_points": 1, "earned_points": 0, "status": "Incorrect",
             "deduction_reason": "Правильный ответ: 3. В работе: 7", "student_answer": ""},
            {"task_number": 2, "max_points": 1, "earned_points": 0, "status": "Not Submitted",
             "deduction_reason": "Ответ не найден", "student_answer": ""},
        ],
    }
    base.update(overrides)
    return base


class TestHtmlEscape:
    def test_escapes_angle_brackets_and_ampersand(self):
        assert html_escape("<b>") == "&lt;b&gt;"
        assert html_escape("a & b") == "a &amp; b"

    def test_existing_tags_survive(self):
        # теги разметки отчёта не экранируются: escape применяется только к пользовательскому тексту
        text = build_telegram_short(result_data())
        assert "<b>" in text and "&lt;" not in text.replace("&amp;", "")


class TestTelegramShort:
    def test_contains_score_and_problems(self):
        text = build_telegram_short(result_data())
        assert "Набрано: 2 из 5 (40%)" in text
        assert "№1" in text and "№2" in text and "№19" in text
        assert "Incorrect" not in text  # статусы на русском не выводим, только эмодзи

    def test_top3_problems_priority(self):
        data = result_data()
        data["task_breakdown"] = [
            {"task_number": i, "max_points": 1, "earned_points": 0, "status": "Incorrect",
             "deduction_reason": f"ошибка {i}", "student_answer": ""}
            for i in range(5)
        ]
        text = build_telegram_short(data)
        assert "№0" in text and "№1" in text and "№2" in text  # топ-3 (стабильный порядок)
        assert "№3" not in text and "№4" not in text
        assert "и другие" in text

    def test_student_html_never_breaks_markup(self):
        data = result_data()
        data["task_breakdown"] = [
            {"task_number": 1, "max_points": 1, "earned_points": 0, "status": "Incorrect",
             "deduction_reason": "В работе: <script>alert('x&y')</script>", "student_answer": ""},
        ]
        text = build_telegram_short(data)
        assert "<script>" not in text
        assert "&lt;script&gt;" in text

    def test_length_limit_huge_reasons(self):
        data = result_data()
        data["task_breakdown"] = [
            {"task_number": i, "max_points": 1, "earned_points": 0, "status": "Incorrect",
             "deduction_reason": "ошибка " * 800, "student_answer": ""}
            for i in range(20)
        ]
        text = build_telegram_short(data)
        assert len(text) <= TG_SHORT_LIMIT
