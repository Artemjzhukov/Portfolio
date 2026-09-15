"""Тесты детерминированных движков: парсинг сегментов и проверка тестов."""

import io

import pytest
from docx import Document

from app.schemas import OCRSegment
from app.services.checker_test import answers_match, check_standard_test, normalize_answer
from app.services.ocr import ExtractionService, merge_segments, parse_segments_from_text

from tests.conftest import FakeLLM


class TestNormalize:
    def test_case_and_yo(self):
        assert normalize_answer("ЁЖИК Ёлка") == "ежик елка"

    def test_punctuation_stripped(self):
        assert normalize_answer('"Александр II."') == "александр ii"

    def test_numeric_comma_normalized_consistently(self):
        assert normalize_answer("3,5") == "3 5"
        assert answers_match("3,5", "3,5")


class TestAnswersMatch:
    def test_exact(self):
        assert answers_match("3", "3")

    def test_numeric_zero_padding(self):
        assert answers_match("03", "3")

    def test_typo_fuzzy(self):
        assert answers_match("Александр Второй", "Александр Втрой")  # опечатка

    def test_wrong(self):
        assert not answers_match("4", "3")

    def test_set_answers_order_insensitive(self):
        assert answers_match("1, 3, 4", "4,1,3")

    def test_set_partial_no_match(self):
        assert not answers_match("1,3", "1,3,4")

    def test_empty_rejected(self):
        assert not answers_match("", "3")


def make_extracted(answers: dict[int, str]):
    return type(
        "E", (), {"segments": [OCRSegment(task_number=n, text=t) for n, t in answers.items()],
                 "unmatched_segments": []}
    )()


class TestCheckStandardTest:
    def test_mixed_results(self):
        extracted = make_extracted({1: "3", 2: "4", 3: "Александр Втрой"})
        breakdowns, unkeyed = check_standard_test(
            extracted, {"1": "3", "2": "5", "3": "Александр Второй", "4": "9"}
        )
        by_num = {b.task_number: b for b in breakdowns}
        assert by_num[1].status == "Correct"
        assert by_num[2].status == "Incorrect"
        assert "Правильный ответ: 5" in by_num[2].deduction_reason
        assert by_num[3].status == "Correct"  # опечатка прощена
        assert by_num[4].status == "Not Submitted"
        assert unkeyed == []

    def test_unkeyed_task_reported(self):
        extracted = make_extracted({1: "3", 7: "лишнее"})
        breakdowns, unkeyed = check_standard_test(extracted, {"1": "3"})
        assert unkeyed == [7]
        assert len(breakdowns) == 1


class TestParseSegments:
    def test_numbered_lines(self):
        text = "Фамилия: Иванов\n№1 Текст ответа один\n№2 Текст ответа два"
        segments, unmatched = parse_segments_from_text(text)
        assert [s.task_number for s in segments] == [1, 2]
        assert segments[1].text == "Текст ответа два"
        assert unmatched and "Иванов" in unmatched[0].text

    def test_year_not_parsed_as_task(self):
        text = "№1 Ответ\n1861 год был важным"
        segments, _ = parse_segments_from_text(text)
        assert len(segments) == 1
        assert "1861" in segments[0].text

    def test_dot_format(self):
        text = "19. Здесь развернутый ответ\nпродолжение ответа\n20. Другой ответ"
        segments, _ = parse_segments_from_text(text)
        assert [s.task_number for s in segments] == [19, 20]
        assert "продолжение" in segments[0].text
        assert segments[0].text.startswith("Здесь")


class TestMergeSegments:
    def test_same_number_merged(self):
        merged = merge_segments([
            OCRSegment(task_number=5, text="часть один", page=1, confidence=0.9),
            OCRSegment(task_number=5, text="часть два", page=2, confidence=0.5),
        ])
        assert len(merged) == 1
        assert merged[0].was_split_across_pages
        assert merged[0].confidence == 0.5
        assert "часть один" in merged[0].text and "часть два" in merged[0].text


class TestExtractionService:
    def test_txt_path(self, settings):
        svc = ExtractionService(llm=FakeLLM(), settings=settings)
        result = svc.extract(file_bytes="№1 ответ три".encode("utf-8"), file_name="work.txt")
        assert result.source_type == "plain_text"
        assert result.segments[0].task_number == 1

    def test_docx_path(self, settings):
        document = Document()
        document.add_paragraph("№12 Мой ответ про реформы")
        buffer = io.BytesIO()
        document.save(buffer)
        svc = ExtractionService(llm=FakeLLM(), settings=settings)
        result = svc.extract(file_bytes=buffer.getvalue(), file_name="work.docx")
        assert result.source_type == "docx"
        assert result.segments[0].task_number == 12

    def test_image_requires_vision_provider(self, settings):
        class NoVisionSettings:
            ocr_confidence_threshold = settings.ocr_confidence_threshold
            min_extracted_chars = settings.min_extracted_chars
            ocr_is_vision_capable = False

        svc = ExtractionService(llm=FakeLLM(), settings=NoVisionSettings())
        with pytest.raises(RuntimeError, match="Vision"):
            svc.extract(file_bytes=b"\xff\xd8\xff\xe0fake", file_name="work.jpg")

    def test_vision_happy_path_with_low_confidence_retry(self, settings):
        fake = FakeLLM(responses=[
            {"pages_count": 1, "segments": [
                {"task_number": 1, "text": "ответ", "page": 1, "confidence": 0.95},
                {"task_number": None, "text": "неразборчиво", "page": 1, "confidence": 0.3},
            ]},
            # второй проход верификации
            {"pages_count": 1, "segments": [
                {"task_number": 2, "text": "неразборчиво (уточнено)", "page": 1, "confidence": 0.9},
            ]},
        ])
        svc = ExtractionService(llm=fake, settings=settings)
        result = svc.extract(file_bytes=b"\xff\xd8\xff\xe0fake", file_name="work.jpg")
        assert result.source_type == "image_ocr"
        assert [s.task_number for s in result.segments] == [1, 2]
        assert len(fake.calls) == 2  # транскрипция + перепроверка
        assert result.unmatched_segments == []
