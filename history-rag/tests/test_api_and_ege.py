"""Тесты ЕГЭ-оценщика (LLM замокан) и API-эндпоинтов."""

import base64

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app
from app.services.checker_ege import EGEEvaluator
from app.services.pipeline import AssessmentPipeline
from app.services.rag import TheoryRetriever

from tests.conftest import FakeLLM


def ege_payload(answer=None):
    return dict(
        file_bytes=base64.b64encode("№19 Какой-то текст".encode("utf-8")).decode(),
        file_name="work.txt",
        submission_type="ege_exam",
        subject_id="history",
        student_id="chat-1",
        **({"answer_key": answer} if answer is not None else {}),
    )


def llm_verdict(k1_points=2, k2_points=1):
    return {
        "criteria_evaluations": [
            {"criterion_id": "K1", "earned_points": k1_points,
             "quote_from_answer": "цитата", "deduction_reason_ru": "" if k1_points == 2 else "не всё"},
            {"criterion_id": "K2", "earned_points": k2_points,
             "quote_from_answer": "цитата", "deduction_reason_ru": "" if k2_points == 1 else "нет связи"},
        ],
        "uncovered_answer_fragments": [],
        "review_reasons_ru": [],
    }


class TestOpenRouterConfig:
    def test_openrouter_base_url_and_model(self, settings):
        """OpenRouter: ключ и модели те же, меняется только base_url."""
        from app.services.llm import OpenAIJSONClient

        settings.openai_api_key = "sk-or-v1-test"
        settings.llm_base_url = "https://openrouter.ai/api/v1"
        settings.openai_eval_model = "openai/gpt-4o"
        client = OpenAIJSONClient(settings)
        assert client._client.base_url.path.rstrip("/") == "/api/v1"
        assert client.model == "openai/gpt-4o"
        assert client.strict  # strict JSON Schema по умолчанию включён

    def test_openrouter_non_strict_fallback(self, settings):
        """llm_strict_json=false -> json_object режим (для моделей без Structured Outputs)."""
        from app.services.llm import OpenAIJSONClient

        settings.llm_base_url = "https://openrouter.ai/api/v1"
        settings.llm_strict_json = False
        client = OpenAIJSONClient(settings)
        assert not client.strict


class TestEGEEvaluator:
    def test_valid_evaluation(self, settings, rubric_task19):
        evaluator = EGEEvaluator(llm=FakeLLM([llm_verdict()]), settings=settings)
        result = evaluator.evaluate_task(rubric_task19, "ответ ученика")
        assert result.earned(rubric_task19) == 3
        assert not result.needs_human_review

    def test_invalid_then_retry(self, settings, rubric_task19):
        # первая попытка: вне ступеней (3 при max 2) -> отброшена; вторая: валидна
        bad = llm_verdict()
        bad["criteria_evaluations"][0]["earned_points"] = 3
        evaluator = EGEEvaluator(llm=FakeLLM([bad, llm_verdict()]), settings=settings)
        result = evaluator.evaluate_task(rubric_task19, "ответ")
        assert result.earned(rubric_task19) == 3
        assert len(evaluator.llm.calls) == 2

    def test_both_invalid_flags_review(self, settings, rubric_task19):
        bad = llm_verdict()
        bad["criteria_evaluations"] = [{"criterion_id": "K1", "earned_points": 9,
                                        "quote_from_answer": "q", "deduction_reason_ru": "r"}]
        evaluator = EGEEvaluator(llm=FakeLLM([bad, bad]), settings=settings)
        result = evaluator.evaluate_task(rubric_task19, "ответ")
        assert result.needs_human_review
        assert result.earned(rubric_task19) == 0

    def test_empty_answer_no_llm(self, settings, rubric_task19):
        evaluator = EGEEvaluator(llm=FakeLLM(), settings=settings)
        result = evaluator.evaluate_task(rubric_task19, "   ")
        assert result.earned(rubric_task19) == 0
        assert evaluator.llm.calls == []

    def test_factcheck_failure_sets_review(self, settings, rubric_task19):
        class FailFactCheck:
            def check(self, quote, topics):
                return None

        evaluator = EGEEvaluator(
            llm=FakeLLM([llm_verdict(k1_points=1, k2_points=0)]),
            settings=settings, factcheck=FailFactCheck(),
        )
        result = evaluator.evaluate_task(rubric_task19, "ответ")
        assert result.needs_human_review
        assert any("не подтверждено" in r for r in result.review_reasons_ru)

    def test_load_rubrics_from_disk(self, settings):
        evaluator = EGEEvaluator(llm=FakeLLM(), settings=settings)
        rubrics = evaluator.load_rubrics("history")
        assert 19 in rubrics
        assert rubrics[19].max_points == 3

    def test_borderline_median_of_three_votes(self, settings, rubric_task19):
        """K1 спорный (1 из 2): голоса 1, 0, 2 -> медиана 1, выбирается первый вердикт с медианой."""
        settings.consistency_votes = 3
        votes = []
        for k1 in (1, 0, 2):
            votes.append({
                "criteria_evaluations": [
                    {"criterion_id": "K1", "earned_points": k1,
                     "quote_from_answer": "цитата",
                     "deduction_reason_ru": "" if k1 == 2 else "не всё"},
                    {"criterion_id": "K2", "earned_points": 1},
                ],
                "uncovered_answer_fragments": [],
                "review_reasons_ru": [],
            })
        evaluator = EGEEvaluator(llm=FakeLLM(votes), settings=settings)
        result = evaluator.evaluate_task(rubric_task19, "ответ")
        k1 = next(e for e in result.criteria_evaluations if e.criterion_id == "K1")
        assert k1.earned_points == 1
        assert result.earned(rubric_task19) == 2  # K1=1 + K2=1
        assert len(evaluator.llm.calls) == 3

    def test_social_studies_rubric_valid(self, settings):
        """Вторая предметная рубрика проходит те же инварианты Pydantic."""
        evaluator = EGEEvaluator(llm=FakeLLM(), settings=settings)
        rubrics = evaluator.load_rubrics("social_studies")
        assert 24 in rubrics
        assert rubrics[24].max_points == 6


class TestPipelineEGE:
    def _pipeline(self, settings, fake_llm):
        return AssessmentPipeline(
            extraction=None,  # подменяется ниже
            ege_evaluator=EGEEvaluator(llm=fake_llm, settings=settings),
            retriever=TheoryRetriever(settings),
        )

    def test_rubric_and_key_tasks_combined(self, settings):
        from app.schemas import ExtractedSubmission, OCRSegment, SubmissionInput

        fake = FakeLLM([llm_verdict(k1_points=1, k2_points=1)])
        pipeline = self._pipeline(settings, fake)
        extracted = ExtractedSubmission(
            source_type="plain_text",
            segments=[
                OCRSegment(task_number=19, text="развернутый ответ"),
                OCRSegment(task_number=1, text="3"),
            ],
        )

        class FixedExtraction:
            def extract(self, *, file_bytes, file_name):
                return extracted

        pipeline.extraction = FixedExtraction()
        payload = SubmissionInput(**ege_payload({"1": "3"}))
        result = pipeline.run(payload, b"x", "work.txt")

        assert result.total_score == 3.0  # K1=1 + K2=1 (задача 19) + 1 (задача 1 по ключу)
        assert result.max_possible_score == 4.0  # 3 (рубрика) + 1 (ключ)
        assert not result.needs_human_review

    def test_no_rubrics_warning(self, settings):
        from app.schemas import ExtractedSubmission, OCRSegment, SubmissionInput

        pipeline = self._pipeline(settings, FakeLLM())
        extracted = ExtractedSubmission(
            source_type="plain_text", segments=[OCRSegment(task_number=30, text="ответ")]
        )

        class FixedExtraction:
            def extract(self, *, file_bytes, file_name):
                return extracted

        pipeline.extraction = FixedExtraction()
        # math: папки рубрик нет -> предупреждение + ручная проверка
        data = ege_payload()
        data["subject_id"] = "math"
        payload = SubmissionInput(**data)
        result = pipeline.run(payload, b"x", "work.txt")
        assert result.needs_human_review
        assert any("рубрики" in w for w in result.warnings)


@pytest.fixture
def client(settings, monkeypatch):
    """API-клиент с подменённым пайплайном (LLM не вызывается)."""
    from app.schemas import AssessmentResult, TaskBreakdown

    monkeypatch.setattr(main_module, "get_settings", lambda: settings)

    class StubPipeline:
        def run(self, payload, file_bytes, file_name):
            return AssessmentResult(
                student_id=payload.student_id,
                subject_id=payload.subject_id,
                submission_type=payload.submission_type,
                total_score=1, max_possible_score=1, percentage=100.0,
                summary_feedback="Итог проверки ok",
                task_breakdown=[TaskBreakdown(task_number=1, max_points=1, earned_points=1,
                                              status="Correct", student_answer="3")],
            )

    monkeypatch.setattr(main_module, "_build_pipeline", lambda: StubPipeline())
    return TestClient(app)


class TestAPI:
    def test_standard_test_ok(self, client):
        resp = client.post("/process-submission", json=dict(
            file_bytes=base64.b64encode("№1 3".encode()).decode(), file_name="w.txt",
            submission_type="standard_test", subject_id="history",
            student_id="s1", answer_key={"1": "3"},
        ))
        assert resp.status_code == 200
        body = resp.json()
        assert body["percentage"] == 100.0
        assert body["task_breakdown"][0]["status"] == "Correct"
        assert "Итог проверки" in body["summary_feedback"]

    def test_both_file_sources_422(self, client):
        resp = client.post("/process-submission", json=dict(
            file_url="http://x", file_bytes="AAAA", submission_type="standard_test",
            subject_id="history", student_id="s1", answer_key={"1": "3"},
        ))
        assert resp.status_code == 422

    def test_missing_answer_key_422(self, client):
        resp = client.post("/process-submission", json=dict(
            file_bytes="AAAA", submission_type="standard_test",
            subject_id="history", student_id="s1",
        ))
        assert resp.status_code == 422

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_pipeline_error_502(self, client, monkeypatch):
        class BoomPipeline:
            def run(self, payload, file_bytes, file_name):
                raise RuntimeError("LLM недоступна")

        monkeypatch.setattr(main_module, "_build_pipeline", lambda: BoomPipeline())
        resp = client.post("/process-submission", json=dict(
            file_bytes="AAAA", file_name="w.txt", submission_type="standard_test",
            subject_id="history", student_id="s1", answer_key={"1": "3"},
        ))
        assert resp.status_code == 502

    def test_api_key_required(self, client, settings, monkeypatch):
        """При заданном API_KEY запрос без X-API-Key -> 401, с ключом -> 200."""
        settings.api_key = "secret-key"
        body = dict(
            file_bytes="AAAA", file_name="w.txt", submission_type="standard_test",
            subject_id="history", student_id="s1", answer_key={"1": "3"},
        )
        resp = client.post("/process-submission", json=body)
        assert resp.status_code == 401
        resp = client.post("/process-submission", json=body, headers={"X-API-Key": "secret-key"})
        assert resp.status_code == 200
        settings.api_key = ""  # вернуть состояние фикстуры

    def test_api_key_wrong_value_401(self, client, settings):
        settings.api_key = "secret-key"
        resp = client.post(
            "/process-submission",
            json=dict(
                file_bytes="AAAA", file_name="w.txt", submission_type="standard_test",
                subject_id="history", student_id="s1", answer_key={"1": "3"},
            ),
            headers={"X-API-Key": "wrong"},
        )
        assert resp.status_code == 401
        settings.api_key = ""

    # ---- асинхронный путь (job store + идемпотентность) ----

    def test_async_flow_and_idempotency(self, client, settings, tmp_path, monkeypatch):
        from app.schemas import AssessmentResult, TaskBreakdown

        settings.jobs_db_path = str(tmp_path / "jobs.db")

        class RealStubPipeline:
            def run(self, payload, file_bytes, file_name, job_id=None):
                return AssessmentResult(
                    student_id=payload.student_id, subject_id=payload.subject_id,
                    submission_type=payload.submission_type,
                    total_score=1, max_possible_score=1, percentage=0,
                    summary_feedback="ok",
                    task_breakdown=[TaskBreakdown(task_number=1, max_points=1,
                                                  earned_points=1, status="Correct")],
                )

        monkeypatch.setattr(main_module, "_build_pipeline", lambda: RealStubPipeline())
        body = dict(
            file_bytes="AAAA", file_name="w.txt", submission_type="standard_test",
            subject_id="history", student_id="s1", answer_key={"1": "3"},
        )

        # 1) первый запрос -> 202 queued, фоновая задача выполнится после ответа
        resp1 = client.post("/process-submission/async", json=body)
        assert resp1.status_code == 202
        job_id = resp1.json()["job_id"]
        assert resp1.json()["reused"] is False

        # 2) джоба посчитана (TestClient исполняет background tasks) -> done + результат
        resp2 = client.get(f"/results/{job_id}")
        assert resp2.status_code == 200
        status = resp2.json()
        assert status["status"] == "done"
        assert status["result"]["total_score"] == 1.0

        # 3) повторный POST того же submission -> done мгновенно, reused=true, без нового расчёта
        resp3 = client.post("/process-submission/async", json=body)
        assert resp3.status_code == 200
        assert resp3.json()["reused"] is True
        assert resp3.json()["result"]["total_score"] == 1.0

    def test_async_error_stored_not_lost(self, client, settings, tmp_path, monkeypatch):
        settings.jobs_db_path = str(tmp_path / "jobs.db")

        class BoomPipeline:
            def run(self, payload, file_bytes, file_name, job_id=None):
                raise RuntimeError("LLM недоступна")

        monkeypatch.setattr(main_module, "_build_pipeline", lambda: BoomPipeline())
        resp = client.post("/process-submission/async", json=dict(
            file_bytes="AAAA", file_name="w.txt", submission_type="standard_test",
            subject_id="history", student_id="s1", answer_key={"1": "3"},
        ))
        assert resp.status_code == 202
        resp2 = client.get(f"/results/{resp.json()['job_id']}")
        body = resp2.json()
        assert body["status"] == "error"
        assert "LLM недоступна" in body["error"]

    def test_unknown_job_404(self, client, settings, tmp_path):
        settings.jobs_db_path = str(tmp_path / "jobs.db")
        resp = client.get("/results/nonexistent")
        assert resp.status_code == 404

    def test_job_id_in_logs(self, client, settings, tmp_path, monkeypatch, caplog):
        """Корреляция: job_id присутствует в логах принятия и жизненного цикла джобы."""
        import logging as logmod

        from app.schemas import AssessmentResult

        settings.jobs_db_path = str(tmp_path / "jobs.db")

        class RealStubPipeline:
            def run(self, payload, file_bytes, file_name, job_id=None):
                return AssessmentResult(
                    student_id=payload.student_id, subject_id=payload.subject_id,
                    submission_type=payload.submission_type,
                    total_score=1, max_possible_score=1, percentage=0,
                    summary_feedback="ok",
                )

        monkeypatch.setattr(main_module, "_build_pipeline", lambda: RealStubPipeline())
        with caplog.at_level(logmod.INFO):
            resp = client.post("/process-submission/async", json=dict(
                file_bytes="AAAA", file_name="w.txt", submission_type="standard_test",
                subject_id="history", student_id="s1", answer_key={"1": "3"},
            ))
            job_id = resp.json()["job_id"]
            client.get(f"/results/{job_id}")

        messages = [record.getMessage() for record in caplog.records]
        assert any(job_id in m for m in messages)
        assert any("accepted new" in m for m in messages)
        assert any("done" in m for m in messages)
