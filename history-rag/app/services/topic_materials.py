"""Материалы тем для закрепления: файл учителя + авто-attach из data/media.

Кто добавляет и куда:
- учитель кладёт файлы в data/media/<тема>/ — они прикрепляются автоматически;
- внешние ссылки и тренажёры — в data/materials/{subject_id}.json.
Ученик ничего не добавляет. Тема привязки — строка topic_ru из roadmap.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.schemas import MaterialLink, SubjectMaterialsFile

logger = logging.getLogger(__name__)


def normalize_topic(topic: str) -> str:
    """Единая нормализация для сопоставления тем: регистр, пробелы, кавычки."""
    return " ".join(topic.replace("«", "").replace("»", "").replace('"', "").split()).casefold()


class TopicMaterialsStore:
    def __init__(self, settings) -> None:
        self.s = settings

    def get(self, subject_id: str, topic_ru: str) -> list[MaterialLink]:
        path = Path(self.s.materials_dir) / f"{subject_id}.json"
        if not path.is_file():
            return []
        data = SubjectMaterialsFile.model_validate_json(path.read_text(encoding="utf-8"))
        if data.subject_id != subject_id:
            raise ValueError(
                f"{path}: subject_id в файле ('{data.subject_id}') != ожидаемому ('{subject_id}')"
            )
        wanted = normalize_topic(topic_ru)
        for name, items in data.topics.items():
            if normalize_topic(name) == wanted:
                return [
                    MaterialLink(title_ru=item.title_ru, url=item.url, kind=item.kind)
                    for item in items
                ]
        return []


def media_links_for_topic(media_dir: Path, topic_ru: str) -> list[MaterialLink]:
    """Все файлы из data/media/<тема>/ становятся ссылками /media/<тема>/<файл>.

    Каталоги и не-файлы пропускаются. Сортировка по имени для стабильности.
    """
    topic_dir = Path(media_dir) / topic_ru
    if not topic_dir.is_dir():
        return []
    items: list[MaterialLink] = []
    for path in sorted(topic_dir.iterdir(), key=lambda p: p.name):
        if not path.is_file():
            continue
        items.append(MaterialLink(title_ru=path.name, url=f"/media/{topic_ru}/{path.name}", kind="file"))
    return items


def resolve_materials(store: TopicMaterialsStore | None, media_dir: Path | None, subject_id: str, topic_ru: str) -> list[MaterialLink]:
    """Файл учителя первым, затем авто-медиа; дедупликация по url с сохранением порядка."""
    file_items = store.get(subject_id, topic_ru) if store is not None else []
    media_items = media_links_for_topic(media_dir, topic_ru) if media_dir is not None else []
    merged: list[MaterialLink] = []
    seen: set[str] = set()
    for item in [*file_items, *media_items]:
        if item.url in seen:
            continue
        seen.add(item.url)
        merged.append(item)
    return merged