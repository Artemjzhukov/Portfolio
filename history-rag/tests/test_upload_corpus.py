"""Тесты загрузчика корпуса: извлечение, чанкинг, метаданные (без сети)."""

from pathlib import Path

import pytest

from scripts.upload_corpus import collect_documents, extract_text, guess_meta


class TestExtractText:
    def test_txt(self, tmp_path):
        f = tmp_path / "doc.txt"
        f.write_text("Привет, история", encoding="utf-8")
        assert extract_text(f) == "Привет, история"

    def test_unsupported(self, tmp_path):
        f = tmp_path / "doc.exe"
        f.write_bytes(b"x")
        with pytest.raises(ValueError, match="Неподдерживаемый формат"):
            extract_text(f)


class TestGuessMeta:
    def test_year_and_topic(self, tmp_path):
        meta = guess_meta(tmp_path / "реформа_1864.txt")
        assert meta["doc_date"] == "1864"

    def test_topic_from_parent(self, tmp_path):
        folder = tmp_path / "Alexander II"
        folder.mkdir()
        meta = guess_meta(folder / "notes.txt")
        assert meta["topic"] == "Alexander II"


class TestCollectDocuments:
    def test_collect_and_chunk(self, tmp_path):
        f = tmp_path / "doc.txt"
        f.write_text("А" * 2000, encoding="utf-8")
        docs = collect_documents(tmp_path, chunk_size=800, chunk_overlap=100)
        assert len(docs) >= 3
        assert docs[0]["source"].startswith("doc.txt#")
        assert docs[0]["topic"] == tmp_path.name

    def test_limit(self, tmp_path):
        for i in range(3):
            (tmp_path / f"d{i}.txt").write_text(f"текст {i}", encoding="utf-8")
        docs = collect_documents(tmp_path, limit=2)
        assert len(docs) == 2

    def test_empty_files_skipped(self, tmp_path):
        (tmp_path / "empty.txt").write_text("", encoding="utf-8")
        assert collect_documents(tmp_path) == []
