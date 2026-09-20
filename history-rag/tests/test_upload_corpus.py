"""Тесты загрузчика корпуса: извлечение, чанкинг, метаданные (без сети)."""

from pathlib import Path

import pytest

from app.services.rag import TheoryRetriever
from scripts.upload_corpus import (
    collect_documents,
    collect_images,
    extract_text,
    guess_meta,
)


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

class TestImages:
    def test_collect_images_copies_and_captions(self, tmp_path):
        media = tmp_path / "media"
        folder = tmp_path / "Alexander II"
        folder.mkdir()
        (folder / "portrait.jpg").write_bytes(b"\xff\xd8fake")
        (folder / "captions.json").write_text(
            '{"portrait.jpg": "Портрет Александра II, 1860-е"}', encoding="utf-8"
        )
        docs = collect_images(folder, media)
        assert len(docs) == 1
        assert docs[0]["image"] == "Alexander II/portrait.jpg"
        assert (media / "Alexander II" / "portrait.jpg").exists()
        assert docs[0]["content"] == "Портрет Александра II, 1860-е"  # подпись из captions

    def test_collect_images_fallback_topic_text(self, tmp_path):
        media = tmp_path / "media"
        folder = tmp_path / "карты"
        folder.mkdir()
        (folder / "krym_1853.png").write_bytes(b"\x89PNGfake")
        docs = collect_images(folder, media)
        assert "Иллюстрация" in docs[0]["content"]
        assert docs[0]["image"] == "карты/krym_1853.png"

    def test_unsupported_images_skipped(self, tmp_path):
        media = tmp_path / "media"
        folder = tmp_path / "topic"
        folder.mkdir()
        (folder / "doc.heic").write_bytes(b"zzz")
        (folder / "readme.txt").write_text("x", encoding="utf-8")
        assert collect_images(folder, media) == []


class TestImageUrl:
    def test_with_public_base(self):
        assert TheoryRetriever.image_url("http://host:8000/media", "t/p.jpg") == "http://host:8000/media/t/p.jpg"

    def test_without_base(self):
        assert TheoryRetriever.image_url("", "t/p.jpg") == "t/p.jpg"

