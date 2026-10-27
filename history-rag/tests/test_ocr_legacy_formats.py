"""Извлечение legacy-форматов: RTF с кодировкой из заголовка и DOCX через python-docx.

Утверждения сравнивают результат с точной ожидаемой строкой: именно этого не
хватало прежней версии тестов, где проверялось «не упало и длина больше нуля».
"""

from __future__ import annotations

import pytest

from app.services.ocr import (
    ExtractionError,
    detect_file_type,
    extract_docx_text,
    extract_rtf_text,
    parse_rtf_codepage,
)

# Сигнатура OLE2-контейнера: так начинается любой Word 97-2003 (.doc).
OLE_DOC_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


class TestRtfEncoding:
    def test_ansicpg1251_is_used(self, make_rtf):
        body = "Смутное время 1612"
        text, encoding = extract_rtf_text(make_rtf(body, 1251), "smuta.rtf")
        assert text == body
        assert encoding == "cp1251"

    def test_ansicpg1252_wins_over_latin1(self, make_rtf):
        # € (0x80) и „ “ (0x84/0x93) в cp1252 — печатные знаки, а в latin-1 —
        # управляющие символы. Кейс ловит прежнюю логику «latin-1 первым».
        body = "Preis 100 €, „Angebot“"
        raw = make_rtf(body, 1252, "cp1252")
        text, encoding = extract_rtf_text(raw, "german.rtf")
        assert text == body
        assert encoding == "cp1252"
        assert text != body.encode("cp1252").decode("latin-1")

    def test_no_ansicpg_falls_back_to_cp1251(self, make_rtf):
        body = "Смута 1605-1613"
        raw = make_rtf(body, None)
        assert parse_rtf_codepage(raw) is None
        text, encoding = extract_rtf_text(raw, "noheader.rtf")
        assert text == body
        assert encoding == "cp1251"

    def test_unknown_ansicpg_still_readable(self, make_rtf):
        # На \ansicpg9999 сам striprtf подставил бы utf8 и упал на UnicodeDecodeError
        # (striprtf.py:296-301) — заголовок выравнивается до нашего кодека.
        body = "Смута 1612"
        raw = make_rtf(body, 9999)
        assert parse_rtf_codepage(raw) is None
        text, encoding = extract_rtf_text(raw, "weird.rtf")
        assert text == body
        assert encoding == "cp1251"

    def test_parse_rtf_codepage(self):
        assert parse_rtf_codepage(b"{\\rtf1\\ansi\\ansicpg1251") == "cp1251"
        assert parse_rtf_codepage(b"{\\rtf1\\ansi\\ansicpg65001") == "utf-8"
        assert parse_rtf_codepage(b"{\\rtf1\\ansi") is None

    def test_surrogate_pairs_merged_into_one_codepoint(self):
        # U+1F600 = high D83D (55357) + low DE00 (56832); в RTF отрицательные числа.
        raw = b"{\\rtf1\\ansi\\ansicpg1251 \\u-10179?\\u-8704? done}"
        text, encoding = extract_rtf_text(raw, "emoji.rtf")
        assert text == "\U0001F600 done"
        assert not any(0xD800 <= ord(ch) <= 0xDFFF for ch in text)
        assert encoding == "cp1251"

    def test_empty_bytes_raises(self):
        with pytest.raises(ExtractionError, match="пустой файл RTF"):
            extract_rtf_text(b"", "empty.rtf")

    def test_not_rtf_raises(self):
        with pytest.raises(ExtractionError, match="не RTF"):
            extract_rtf_text(b"<html>not rtf</html>", "fake.rtf")


class TestDocxExtraction:
    def test_paragraphs_and_table(self, make_docx):
        raw = make_docx(
            ["Смутное время", "1605-1613"],
            [["Борис Годунов", "1598"], ["Лжедмитрий I", "1605"]],
        )
        assert extract_docx_text(raw) == (
            "Смутное время\n"
            "1605-1613\n"
            "Борис Годунов | 1598\n"
            "Лжедмитрий I | 1605"
        )

    def test_empty_document_returns_empty_string(self, make_docx):
        assert extract_docx_text(make_docx([])) == ""

    def test_broken_zip_raises(self):
        with pytest.raises(ExtractionError, match="DOCX не открывается"):
            extract_docx_text(b"not a zip at all")

    def test_zero_bytes_raises(self):
        with pytest.raises(ExtractionError):
            extract_docx_text(b"")


class TestDetectFileType:
    def test_rtf_by_magic(self):
        assert detect_file_type(b"{\\rtf1\\ansi", "x.rtf") == "rtf"

    def test_rtf_without_extension(self):
        assert detect_file_type(b"{\\rtf1", "no_ext") == "rtf"

    def test_ole_doc_by_magic(self):
        assert detect_file_type(OLE_DOC_HEADER, "x.doc") == "doc_legacy"

    def test_doc_extension_fallback_is_doc_legacy(self):
        # Магия OLE не найдена, но расширение .doc: помечаем как doc_legacy,
        # чтобы загрузчик честно сообщил «без конвертации», а не «unknown».
        assert detect_file_type(b"plain text", "x.doc") == "doc_legacy"
