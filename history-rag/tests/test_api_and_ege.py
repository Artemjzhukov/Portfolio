"""Тесты ЕГЭ-оценщика (LLM замокан) и API-эндпоинтов."""

import base64

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app
from app.schemas import TaskRubric
from app.services.checker_ege import EGEEvaluator
from app.services.pipeline import AssessmentPipeline
from app.services.rag import TheoryRetriever

from tests.conftest import FakeLLM


class TestAllRubricsOnDisk:
    """Каждый JSON в data/criteria/** обязан проходить все инварианты TaskRubric."""

    def test_all_rubrics_valid(self):
        from pathlib import Path

        files = sorted(Path("data/criteria").glob("*/*.json"))
        assert files, "нет ни одного файла рубрик"
        for path in files:
            rubric = TaskRubric.model_validate_json(path.read_text(encoding="utf-8"))
            assert rubric.max_points > 0
            for crit in rubric.criteria:
                pts = {s.points for s in crit.deduction_ladder}
                assert crit.max_points in pts, path
                assert 0 in pts, path



def ege_payload(answer=None):
    return dict(
        file_bytes=base64.b64encode("№19 Какой-то текст".encode("utf-8")).decode(),
        file_name="work.txt",
        submission_type="ege_exam",
        subject_id="history",
        student_id="chat-1",
        **({"answer_key": answer} if answer is not None else {}),
    )


def llm_verdict(k1_points=1, k2_points=1):
    return {
        "criteria_evaluations": [
            {"criterion_id": "K1", "earned_points": k1_points,
             "quote_from_answer": "цитата", "deduction_reason_ru": "" if k1_points == 1 else "не всё"},
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
        evaluator = EGEEvaluator(llm=FakeLLM([llm_verdict(), llm_verdict()]), settings=settings)
        result = evaluator.evaluate_task(rubric_task19, "ответ ученика")
        assert result.earned(rubric_task19) == 2
        assert not result.needs_human_review
        result = evaluator.evaluate_task(rubric_task19, "ответ ученика")
        assert result.earned(rubric_task19) == 2
        assert not result.needs_human_review

    def test_invalid_then_retry(self, settings, rubric_task19):
        # первая попытка: вне ступеней (5 при max 1) -> отброшена; вторая: валидна
        bad = llm_verdict()
        bad["criteria_evaluations"][0]["earned_points"] = 5
        evaluator = EGEEvaluator(llm=FakeLLM([bad, llm_verdict()]), settings=settings)
        result = evaluator.evaluate_task(rubric_task19, "ответ")
        assert result.earned(rubric_task19) == 2
        assert len(evaluator.llm.calls) == 2

    def test_both_invalid_raises_verdict_error(self, settings, rubric_task19):
        """Обе попытки невалидны -> LLMVerdictError, а не 0 баллов как оценка."""
        from app.services.llm import LLMVerdictError

        bad = llm_verdict()
        bad["criteria_evaluations"] = [
            {"criterion_id": "K1", "earned_points": 9,
             "quote_from_answer": "q", "deduction_reason_ru": "r"},
        ]
        evaluator = EGEEvaluator(llm=FakeLLM([bad, bad]), settings=settings)
        with pytest.raises(LLMVerdictError, match="LLM_INVALID_VERDICT"):
            evaluator.evaluate_task(rubric_task19, "ответ")

    def test_second_attempt_valid_scores(self, settings, rubric_task19):
        """Первая попытка битая, вторая валидна -> оценка по второй, без ошибки."""
        bad = llm_verdict()
        bad["criteria_evaluations"] = [
            {"criterion_id": "K1", "earned_points": 9,
             "quote_from_answer": "q", "deduction_reason_ru": "r"},
        ]
        evaluator = EGEEvaluator(llm=FakeLLM([bad, llm_verdict()]), settings=settings)
        result = evaluator.evaluate_task(rubric_task19, "ответ ученика")
        assert result.earned(rubric_task19) == 2
        assert not result.needs_human_review

    def test_empty_answer_scores_zero_without_llm(self, settings, rubric_task19):
        """Пустой ответ -> 0 баллов состоявшейся оценкой, LLM не вызывается."""
        evaluator = EGEEvaluator(llm=FakeLLM([]), settings=settings)
        result = evaluator.evaluate_task(rubric_task19, "   ")
        assert result.earned(rubric_task19) == 0
        assert len(evaluator.llm.calls) == 0

    def test_empty_answer_no_llm(self, settings, rubric_task19):
        evaluator = EGEEvaluator(llm=FakeLLM(), settings=settings)
        result = evaluator.evaluate_task(rubric_task19, "   ")
        assert result.earned(rubric_task19) == 0
        assert evaluator.llm.calls == []

    def test_factcheck_failure_sets_review(self, settings, rubric_task19):
        from app.schemas import FactCheckResult

        class FailFactCheck:
            def check(self, quote, topics):
                return None

            def check_detailed(self, quote, topics):
                return FactCheckResult(status="unconfirmed")

        evaluator = EGEEvaluator(
            llm=FakeLLM([llm_verdict(k1_points=1, k2_points=0)]),
            settings=settings, factcheck=FailFactCheck(),
        )
        result = evaluator.evaluate_task(rubric_task19, "ответ")
        assert result.needs_human_review
        assert any("релевантные материалы" in r for r in result.review_reasons_ru)

    def test_load_rubrics_from_disk(self, settings):
        evaluator = EGEEvaluator(llm=FakeLLM(), settings=settings)
        rubrics = evaluator.load_rubrics("history", "2025")
        assert set(rubrics) == {18, 19, 20, 21}
        assert rubrics[18].max_points == 3  # причинно-следственные связи
        assert rubrics[19].max_points == 2  # понятие + факт
        assert rubrics[20].max_points == 3  # сравнение
        assert rubrics[21].max_points == 3  # аргументация
        assert all(r.year_variant == "2025" for r in rubrics.values())

    def test_year_priority_over_unyearned(self, settings, tmp_path):
        """task_{N}_{год}.json побеждает task_{N}.json при запросе этого года."""
        import json

        from app.schemas import TaskRubric

        d = tmp_path / "criteria" / "subj"
        d.mkdir(parents=True)
        base = {
            "schema_version": 1, "subject_id": "subj", "task_number": 1,
            "max_points": 1, "part": 2,
            "criteria": [{"criterion_id": "K1", "title_ru": "T", "description_ru": "D",
                          "max_points": 1,
                          "deduction_ladder": [{"points": 0, "condition_ru": "нет"},
                                               {"points": 1, "condition_ru": "да"}]}],
        }
        (d / "task_1.json").write_text(json.dumps({**base, "year_variant": "2024"}), encoding="utf-8")
        (d / "task_1_2025.json").write_text(json.dumps({**base, "year_variant": "2025"}), encoding="utf-8")
        settings.criteria_dir = tmp_path / "criteria"
        evaluator = EGEEvaluator(llm=FakeLLM(), settings=settings)
        assert evaluator.load_rubrics("subj", "2025")[1].year_variant == "2025"
        assert evaluator.load_rubrics("subj", "2024")[1].year_variant == "2024"

    def test_year_mismatch_in_file_is_loud_error(self, settings, tmp_path):
        """Год в имени != году внутри — ValueError, а не тихая неверная оценка."""
        import json

        import pytest

        d = tmp_path / "criteria" / "subj"
        d.mkdir(parents=True)
        (d / "task_1_2025.json").write_text(json.dumps({
            "schema_version": 1, "subject_id": "subj", "task_number": 1,
            "year_variant": "2024", "max_points": 1, "part": 2,
            "criteria": [{"criterion_id": "K1", "title_ru": "T", "description_ru": "D",
                          "max_points": 1,
                          "deduction_ladder": [{"points": 0, "condition_ru": "нет"},
                                               {"points": 1, "condition_ru": "да"}]}],
        }), encoding="utf-8")
        settings.criteria_dir = tmp_path / "criteria"
        evaluator = EGEEvaluator(llm=FakeLLM(), settings=settings)
        with pytest.raises(ValueError, match="year_variant"):
            evaluator.load_rubrics("subj", "2025")

    def test_borderline_median_of_three_votes(self, settings):
        """K1 спорный (1 из 2): голоса 1, 2, 0 -> медиана 1. Итог K1=1 + K2=1."""
        from app.schemas import RubricCriterion, TaskRubric

        rubric = TaskRubric(
            schema_version=1, subject_id="history", task_number=19,
            year_variant="2025", max_points=3, part=2,
            criteria=[
                RubricCriterion(
                    criterion_id="K1", title_ru="T1", description_ru="D1", max_points=2,
                    deduction_ladder=[
                        {"points": 0, "condition_ru": "нет"},
                        {"points": 1, "condition_ru": "часть"},
                        {"points": 2, "condition_ru": "всё"},
                    ],
                ),
                RubricCriterion(
                    criterion_id="K2", title_ru="T2", description_ru="D2", max_points=1,
                    deduction_ladder=[
                        {"points": 0, "condition_ru": "нет"},
                        {"points": 1, "condition_ru": "да"},
                    ],
                ),
            ],
        )
        settings.consistency_votes = 3
        votes = []
        for k1 in (1, 2, 0):
            votes.append({
                "criteria_evaluations": [
                    {"criterion_id": "K1", "earned_points": k1,
                     "quote_from_answer": "цитата",
                     "deduction_reason_ru": "" if k1 == 2 else "не всё"},
                    {"criterion_id": "K2", "earned_points": 1,
                     "quote_from_answer": "", "deduction_reason_ru": ""},
                ],
                "uncovered_answer_fragments": [],
                "review_reasons_ru": [],
            })
        evaluator = EGEEvaluator(llm=FakeLLM(votes), settings=settings)
        result = evaluator.evaluate_task(rubric, "ответ")
        k1 = next(e for e in result.criteria_evaluations if e.criterion_id == "K1")
        assert k1.earned_points == 1
        assert result.earned(rubric) == 2  # K1=1 (медиана [2,1,0]) + K2=1
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

    def test_rubric_and_key_tasks_combined(self, settings, tmp_path):
        from app.schemas import ExtractedSubmission, OCRSegment, SubmissionInput

        # изолируем набор рубрик (копия task_19_2025.json как task_19.json)
        import shutil

        settings.criteria_dir = tmp_path / "criteria"
        (settings.criteria_dir / "history").mkdir(parents=True)
        shutil.copy(
            "data/criteria/history/task_19_2025.json",
            settings.criteria_dir / "history" / "task_19_2025.json",
        )

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
        assert result.max_possible_score == 3.0  # 2 (рубрика) + 1 (ключ)
        assert not result.needs_human_review

    def test_pipeline_propagates_factcheck_and_recommendation(self, settings):
        """6. Сквозной: unavailable фактчек -> review + warnings + пометка в telegram_short;
        недоступные рекомендации -> warnings, но БЕЗ review за них."""
        from app.schemas import ExtractedSubmission, OCRSegment, SubmissionInput
        from app.services.rag import FactChecker

        class DeadRetriever:
            unavailable_reason = "RAG недоступен (Qdrant localhost:6333): refused"

            def search(self, *a, **k):
                return []

            def recommend(self, subject_id, task_number, query_text):
                from app.schemas import RAGRecommendation
                return RAGRecommendation(
                    task_number=task_number, query_text=query_text,
                    unavailable_reason=self.unavailable_reason,
                )

        pipeline = self._pipeline(
            settings, FakeLLM([llm_verdict(k1_points=1, k2_points=0)]),
        )
        dead = DeadRetriever()
        pipeline.retriever = dead
        pipeline.ege.factcheck = FactChecker(dead)

        extracted = ExtractedSubmission(
            source_type="plain_text",
            segments=[OCRSegment(task_number=19, text="развернутый ответ")],
        )

        class FixedExtraction:
            def extract(self, *, file_bytes, file_name):
                return extracted

        pipeline.extraction = FixedExtraction()
        result = pipeline.run(SubmissionInput(**ege_payload()), b"x", "work.txt")

        assert result.needs_human_review  # основание — невыполненный фактчек
        assert any("rag_unavailable" in w for w in result.warnings)
        assert "Проверка фактов была недоступна" in result.telegram_short
        assert any("рекомендации материалов недоступны" in w for w in result.warnings)
        assert result.total_score == 1.0  # K1=1 + K2=0: баллы не пересчитаны

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


class TestFactCheckStatuses:
    """П.5: четыре статуса фактчека, различимые сквозно до результата."""

    def _k2_deducted(self):
        # K2 снижен (0 из 1) с цитатой и topics -> фактчек обязателен
        return llm_verdict(k1_points=1, k2_points=0)

    def test_unavailable_rag_sets_review(self, settings, rubric_task19):
        """1. RAG недоступен -> unavailable + review + причина rag_unavailable."""
        from app.services.rag import FactChecker

        class DeadRetriever:
            unavailable_reason = "RAG недоступен (Qdrant localhost:6333): refused"

            def search(self, *a, **k):
                return []

        evaluator = EGEEvaluator(
            llm=FakeLLM([self._k2_deducted()]), settings=settings,
            factcheck=FactChecker(DeadRetriever()),
        )
        result = evaluator.evaluate_task(rubric_task19, "ответ")
        k2 = next(e for e in result.criteria_evaluations if e.criterion_id == "K2")
        assert k2.factcheck_status == "unavailable"
        assert result.needs_human_review
        assert any("rag_unavailable" in r for r in result.review_reasons_ru)
        assert result.earned(rubric_task19) == 1  # баллы не пересчитываем

    def test_unconfirmed_keeps_review_without_unavailable_text(self, settings, rubric_task19):
        """2. Поиск выполнен, материалов нет -> unconfirmed, без лжи про недоступность."""
        from app.services.rag import FactChecker

        class EmptyRetriever:
            unavailable_reason = ""

            def search(self, *a, **k):
                return []

        evaluator = EGEEvaluator(
            llm=FakeLLM([self._k2_deducted()]), settings=settings,
            factcheck=FactChecker(EmptyRetriever()),
        )
        result = evaluator.evaluate_task(rubric_task19, "ответ")
        k2 = next(e for e in result.criteria_evaluations if e.criterion_id == "K2")
        assert k2.factcheck_status == "unconfirmed"
        assert result.needs_human_review
        assert any("релевантные материалы" in r for r in result.review_reasons_ru)
        assert not any("недоступ" in r for r in result.review_reasons_ru)
        assert any("не опровержение" in r for r in result.review_reasons_ru)

    def test_deduction_without_quote_never_reaches_factcheck(self, settings, rubric_task19):
        """Снижение без цитаты отсекается валидацией раньше фактчека.

        Вердикт без цитаты отбрасывается в _evaluate_once (validate_evaluation),
        критерий попадает в problems как «не оценён», фактчек по нему не
        вызывается. Частично валидный итог (K1) + review по K2 — это поведение
        пункта 2 (LLMVerdictError только при полностью пустом вердикте).
        """
        from app.services.rag import FactChecker

        calls: list = []

        class SpyRetriever:
            unavailable_reason = ""

            def search(self, *a, **k):
                calls.append((a, k))
                return []

        no_quote = llm_verdict(k1_points=1, k2_points=0)
        no_quote["criteria_evaluations"][1]["quote_from_answer"] = "   "
        evaluator = EGEEvaluator(
            llm=FakeLLM([no_quote, no_quote]), settings=settings,
            factcheck=FactChecker(SpyRetriever()),
        )
        result = evaluator.evaluate_task(rubric_task19, "ответ")
        # K2 без цитаты не прошёл валидацию -> фактчек не вызывался вообще
        assert calls == []
        assert result.needs_human_review
        assert any("K2 не оценён" in r for r in result.review_reasons_ru)

    def test_retrieval_hit_no_factcheck_review(self, settings, rubric_task19):
        """3. Поиск вернул материалы -> retrieval_hit, review по фактчеку нет.

        retrieval_hit означает только наличие материалов, а не верифицированную
        истинность утверждения: даже чанк, не подтверждающий цитату,
        даёт retrieval_hit (ретривер не выносит вердикт об истинности).
        """
        from app.schemas import RAGChunk
        from app.services.rag import FactChecker

        class GoodRetriever:
            unavailable_reason = ""

            def search(self, *a, **k):
                # чанк из хранилища есть, но цитату ученика не подтверждает
                return [RAGChunk(text="рецепт борща: свёкла, капуста, мясо")]

        evaluator = EGEEvaluator(
            llm=FakeLLM([self._k2_deducted()]), settings=settings,
            factcheck=FactChecker(GoodRetriever()),
        )
        result = evaluator.evaluate_task(rubric_task19, "ответ")
        k2 = next(e for e in result.criteria_evaluations if e.criterion_id == "K2")
        assert k2.factcheck_status == "retrieval_hit"
        assert not result.needs_human_review

    def test_not_required_no_check_call(self, settings, rubric_task19):
        """4. Снижения нет -> not_required, проверка не вызывается, review нет."""
        from app.services.rag import FactChecker

        calls: list = []

        class SpyRetriever:
            unavailable_reason = ""

            def search(self, *a, **k):
                calls.append((a, k))
                return []

        evaluator = EGEEvaluator(
            llm=FakeLLM([llm_verdict()]), settings=settings,
            factcheck=FactChecker(SpyRetriever()),
        )
        result = evaluator.evaluate_task(rubric_task19, "ответ")
        assert calls == []
        assert all(e.factcheck_status == "not_required" for e in result.criteria_evaluations)
        assert not result.needs_human_review

    def test_missing_factcheck_dependency_is_unavailable(self, settings, rubric_task19):
        """5. factcheck=None при обязательном фактчеке -> unavailable, не молчание."""
        evaluator = EGEEvaluator(
            llm=FakeLLM([self._k2_deducted()]), settings=settings, factcheck=None,
        )
        result = evaluator.evaluate_task(rubric_task19, "ответ")
        k2 = next(e for e in result.criteria_evaluations if e.criterion_id == "K2")
        assert k2.factcheck_status == "unavailable"
        assert result.needs_human_review
        assert any("factcheck_unavailable" in r for r in result.review_reasons_ru)


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

    def test_answer_key_optional_via_store(self, client, settings, tmp_path, monkeypatch):
        """answer_key не передаётся — эталоны берутся из data/answer_keys/{subject}.json."""
        settings.answer_keys_dir = tmp_path
        (tmp_path / "history.json").write_text(
            '{"schema_version": 1, "subject_id": "history", "answers": {"1": "3"}}',
            encoding="utf-8",
        )
        resp = client.post("/process-submission", json=dict(
            file_bytes="AAAA", file_name="w.txt", submission_type="standard_test",
            subject_id="history", student_id="s1",
        ))
        assert resp.status_code == 200

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

    def test_async_stores_sha256_of_full_file(self, client, settings, tmp_path, monkeypatch):
        """В jobs.file_hash — SHA-256 всего файла, а не hex первых 16 байт.

        Два файла с общим 16-байтным префиксом при старом коде давали
        одинаковый file_hash (коллизия аудита); job_id при этом различался.
        """
        import base64
        import hashlib

        from app.jobs import JobStore
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

        prefix = b"A" * 16
        file_a = prefix + b"XXX-answers"
        file_b = prefix + b"YYY-answers"
        assert file_a.hex()[:32] == file_b.hex()[:32]  # старый код давал коллизию

        def post(content: bytes):
            return client.post("/process-submission/async", json=dict(
                file_bytes=base64.b64encode(content).decode(), file_name="w.txt",
                submission_type="standard_test",
                subject_id="history", student_id="s1", answer_key={"1": "3"},
            ))

        job_a = post(file_a).json()["job_id"]
        job_b = post(file_b).json()["job_id"]
        assert job_a != job_b

        store = JobStore(settings.jobs_db_path)
        assert store.get(job_a)["file_hash"] == hashlib.sha256(file_a).hexdigest()
        assert store.get(job_b)["file_hash"] == hashlib.sha256(file_b).hexdigest()

    def test_async_verdict_error_stored(self, client, settings, tmp_path, monkeypatch):
        """Сквозной: дважды невалидный вердикт -> status=error, LLM_INVALID_VERDICT.

        Проверяет сохранённое состояние задания (GET /results) и отсутствие
        записи в results (балла нет — оценка не состоялась).
        """
        from app.jobs import JobStore

        settings.jobs_db_path = str(tmp_path / "jobs.db")

        bad = llm_verdict()
        bad["criteria_evaluations"] = [
            {"criterion_id": "K1", "earned_points": 9,
             "quote_from_answer": "q", "deduction_reason_ru": "r"},
        ]
        pipeline = TestPipelineEGE()._pipeline(settings, FakeLLM([bad, bad]))

        from app.schemas import ExtractedSubmission, OCRSegment

        class FixedExtraction:
            def extract(self, *, file_bytes, file_name):
                return ExtractedSubmission(
                    source_type="plain_text",
                    segments=[OCRSegment(task_number=19, text="развернутый ответ")],
                )

        pipeline.extraction = FixedExtraction()
        monkeypatch.setattr(main_module, "_build_pipeline", lambda: pipeline)

        import base64 as _b64
        resp = client.post("/process-submission/async", json=dict(
            file_bytes=_b64.b64encode("№19 Какой-то текст".encode()).decode(),
            file_name="work.txt", submission_type="ege_exam",
            subject_id="history", student_id="chat-1", answer_key={"1": "3"},
        ))
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]

        status = client.get(f"/results/{job_id}").json()
        assert status["status"] == "error"
        assert "LLM_INVALID_VERDICT" in (status["error"] or "")
        assert status["result"] is None
        assert JobStore(settings.jobs_db_path).get_result_record(job_id) is None

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

    def test_async_saves_evaluation_record(self, client, settings, tmp_path, monkeypatch):
        """После set_done фоновая джоба сохраняет EvaluationRecord в results (без повторного LLM)."""
        from app.jobs import JobStore
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
        resp = client.post("/process-submission/async", json=dict(
            file_bytes="AAAA", file_name="w.txt", submission_type="standard_test",
            subject_id="history", student_id="s1", answer_key={"1": "3"},
            test_name="Вариант 3",
        ))
        job_id = resp.json()["job_id"]
        record = JobStore(settings.jobs_db_path).get_result_record(job_id)
        assert record is not None
        assert record["test_title"] == "Вариант 3"
        assert record["total_score"] == 1.0
        assert record["student_id"] == "s1"

    def test_async_failure_saves_no_record(self, client, settings, tmp_path, monkeypatch):
        """При ошибке пайплайна запись в results не появляется."""
        from app.jobs import JobStore

        settings.jobs_db_path = str(tmp_path / "jobs.db")

        class BoomPipeline:
            def run(self, payload, file_bytes, file_name, job_id=None):
                raise RuntimeError("бум")

        monkeypatch.setattr(main_module, "_build_pipeline", lambda: BoomPipeline())
        resp = client.post("/process-submission/async", json=dict(
            file_bytes="AAAA", file_name="w.txt", submission_type="standard_test",
            subject_id="history", student_id="s1", answer_key={"1": "3"},
        ))
        assert JobStore(settings.jobs_db_path).get_result_record(resp.json()["job_id"]) is None
