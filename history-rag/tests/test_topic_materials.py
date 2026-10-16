"""Тесты материалов тем: файл учителя, авто-медиа, привязка к roadmap."""

from pathlib import Path

import pytest

from app.schemas import MaterialLink, SubjectMaterialsFile


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


class TestAllMaterialsOnDisk:
    """Каждый JSON в data/materials/** обязан проходить SubjectMaterialsFile + валидацию URL."""

    def test_all_materials_files_valid(self):
        files = sorted(Path("data/materials").glob("*.json"))
        assert files, "нет ни одного файла материалов"
        for path in files:
            data = SubjectMaterialsFile.model_validate_json(path.read_text(encoding="utf-8"))
            assert data.subject_id == path.stem, path
            for topic, items in data.topics.items():
                assert topic.strip(), path
                for item in items:
                    assert isinstance(item, MaterialLink), path


class TestMaterialsFile:
    def test_loads_subject_file(self, settings, tmp_path):
        from app.services.topic_materials import TopicMaterialsStore

        settings.materials_dir = tmp_path
        write(tmp_path / "history.json", '{"schema_version": 1, "subject_id": "history",'
              ' "topics": {"Отмена крепостного права": ['
              '{"title_ru": "Тренажёр", "url": "https://example.com/t", "kind": "link"}]}}')
        store = TopicMaterialsStore(settings)
        items = store.get("history", "Отмена крепостного права")
        assert len(items) == 1
        assert isinstance(items[0], MaterialLink)
        assert items[0].title_ru == "Тренажёр"

    def test_missing_file_empty(self, settings, tmp_path):
        from app.services.topic_materials import TopicMaterialsStore

        settings.materials_dir = tmp_path
        assert TopicMaterialsStore(settings).get("history", "X") == []

    def test_wrong_subject_rejected(self, settings, tmp_path):
        from app.services.topic_materials import TopicMaterialsStore

        settings.materials_dir = tmp_path
        write(tmp_path / "history.json", '{"schema_version": 1, "subject_id": "math", "topics": {}}')
        with pytest.raises(ValueError, match="history"):
            TopicMaterialsStore(settings).get("history", "X")

    def test_bad_url_rejected(self, settings, tmp_path):
        from app.services.topic_materials import TopicMaterialsStore

        settings.materials_dir = tmp_path
        write(tmp_path / "history.json", '{"schema_version": 1, "subject_id": "history",'
              ' "topics": {"T": [{"title_ru": "x", "url": "ftp://e.com/f", "kind": "link"}]}}')
        with pytest.raises(ValueError, match="https?://"):
            TopicMaterialsStore(settings).get("history", "T")


class TestMediaAutoAttach:
    def test_media_files_become_links(self, settings, tmp_path):
        from app.services.topic_materials import media_links_for_topic

        media = tmp_path / "media"
        topic_dir = media / "Карты"
        topic_dir.mkdir(parents=True)
        (topic_dir / "krym.png").write_bytes(b"\x89PNGfake")
        (topic_dir / "notes.txt").write_text("x", encoding="utf-8")
        items = media_links_for_topic(media, "Карты")
        assert len(items) == 2
        assert items[0].kind == "file"
        assert items[0].url == "/media/Карты/krym.png"
        assert all(isinstance(i, MaterialLink) for i in items)

    def test_missing_topic_dir_empty(self, settings, tmp_path):
        from app.services.topic_materials import media_links_for_topic

        assert media_links_for_topic(tmp_path / "media", "Нет такой темы") == []

    def test_broken_symlink_or_dir_skipped(self, tmp_path):
        from app.services.topic_materials import media_links_for_topic

        topic_dir = tmp_path / "T"
        topic_dir.mkdir(parents=True)
        (topic_dir / "sub").mkdir()
        assert media_links_for_topic(tmp_path, "T") == []

    def test_resolve_merges_and_dedupes(self, settings, tmp_path):
        from app.services.topic_materials import TopicMaterialsStore, resolve_materials

        settings.materials_dir = tmp_path
        media = tmp_path / "media"
        topic_dir = media / "T"
        topic_dir.mkdir(parents=True)
        (topic_dir / "a.png").write_bytes(b"\x89PNGfake")
        write(tmp_path / "history.json", '{"schema_version": 1, "subject_id": "history",'
              ' "topics": {"T": ['
              '{"title_ru": "Тренажёр", "url": "https://example.com/t", "kind": "link"},'
              '{"title_ru": "a.png", "url": "/media/T/a.png", "kind": "file"}]}}')
        merged = resolve_materials(TopicMaterialsStore(settings), media, "history", "T")
        assert [m.title_ru for m in merged] == ["Тренажёр", "a.png"]
        assert merged[1].url == "/media/T/a.png"


class TestDashboardBinding:
    def _rows(self):
        return [{
            "job_id": "j1", "student_id": "s1", "subject_id": "history",
            "submission_type": "standard_test", "test_name": None, "test_title": "T",
            "total_score": 0, "max_possible_score": 1, "percentage": 0.0,
            "task_breakdown": [{
                "task_number": 1, "max_points": 1, "earned_points": 0, "status": "Incorrect",
                "student_answer": "x", "correct_answer_or_criteria": "y",
                "deduction_reason": "r", "recommended_topics": "Отмена крепостного права",
                "needs_human_review": False,
            }],
            "needs_human_review": False, "evaluated_at": 100.0,
        }]

    def test_topic_carries_materials(self, settings, tmp_path):
        from app.jobs import JobStore
        from app.services.dashboard import build_student_dashboard
        from app.services.topic_materials import TopicMaterialsStore

        settings.materials_dir = tmp_path
        settings.media_dir = tmp_path / "media"
        write(tmp_path / "history.json", '{"schema_version": 1, "subject_id": "history",'
              ' "topics": {"Отмена крепостного права": ['
              '{"title_ru": "Тренажёр", "url": "https://example.com/t", "kind": "link"}]}}')

        class FakeStore:
            def list_recent(self, student_id, limit=10):
                return self._rows()[:limit]

            def count_results(self, student_id):
                return 1

            def _rows(self):
                return TestDashboardBinding()._rows()

        dash = build_student_dashboard(
            FakeStore(), "s1", materials_store=TopicMaterialsStore(settings),
            media_dir=settings.media_dir,
        )
        assert len(dash.roadmap[0].materials) == 1
        assert dash.roadmap[0].materials[0].title_ru == "Тренажёр"
