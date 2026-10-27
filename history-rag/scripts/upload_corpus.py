# -*- coding: utf-8 -*-
"""Загрузка части корпуса истории в Qdrant для проверки RAG-воркфлоу.

Использование (из папки history-rag):
    python scripts/upload_corpus.py --dir history_database --limit 3
    python scripts/upload_corpus.py --dir D:\\corpus --chunk-size 800
    python scripts/upload_corpus.py --dir ... --dry-run

Переопределение подключения к Qdrant: --host, --port, --collection
(по умолчанию берутся из .env). Формат источников: .txt, .md, .docx, .pdf.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

SUPPORTED = {".txt", ".md", ".docx", ".pdf", ".rtf"}
# Старый бинарный Word (.doc) python-docx не читает, а LibreOffice в этом патче
# не участвует — такие файлы считаем отдельно и честно сообщаем, а не молча
# пропускаем и не выдаём за обработанные.
LEGACY_DOC = {".doc"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
_YEAR_RE = re.compile(r"(1[0-9]{3}|20[0-9]{2})")


@dataclass(frozen=True)
class ExtractedSource:
    """Результат извлечения одного файла: текст + чем он оказался на самом деле.

    detected_format считается по магическим байтам, а не по расширению, поэтому
    файл .rtf с HTML внутри честно помечается как unknown. encoding — фактически
    применённая кодировка (для RTF берётся из \\ansicpgN в заголовке).
    """

    text: str
    detected_format: str
    encoding: Optional[str]
    sha256: str


def extract_source(path: Path) -> ExtractedSource:
    """Текст файла и метаданные извлечения: единственное место чтения с диска."""
    suffix = path.suffix.lower()
    raw = path.read_bytes()
    from app.services.ocr import detect_file_type

    detected = detect_file_type(raw[:8], path.name)
    encoding: Optional[str] = None
    if suffix in (".txt", ".md"):
        text = raw.decode("utf-8", errors="replace")
        encoding = "utf-8"
    elif suffix == ".rtf":
        from app.services.ocr import extract_rtf_text

        text, encoding = extract_rtf_text(raw, path.name)
    elif suffix == ".docx":
        from app.services.ocr import extract_docx_text

        text = extract_docx_text(raw)
    elif suffix == ".pdf":
        from app.services.ocr import extract_pdf_pages

        text = "\n".join(extract_pdf_pages(raw))
    else:
        raise ValueError(f"Неподдерживаемый формат: {path}")
    return ExtractedSource(text=text, detected_format=detected, encoding=encoding, sha256=hashlib.sha256(raw).hexdigest())


def extract_text(path: Path) -> str:
    """Только текст — прежний публичный API загрузчика."""
    return extract_source(path).text


def guess_meta(path: Path) -> dict:
    """topic — имя родительской папки или имя файла; doc_date — год из имени файла."""
    topic = path.parent.name if path.parent.name.lower() not in ("", ".") else path.stem
    match = _YEAR_RE.search(path.stem)
    return {"topic": topic, "doc_date": match.group(0) if match else None}


def load_captions(image_path: Path) -> str | None:
    """Опциональный captions.json рядом с фото: {\"файл.jpg\": \"подпись для поиска\"}."""
    captions_file = image_path.parent / "captions.json"
    if not captions_file.is_file():
        return None
    try:
        import json

        data = json.loads(captions_file.read_text(encoding="utf-8-sig"))
        caption = data.get(image_path.name)
        return caption.strip() if isinstance(caption, str) and caption.strip() else None
    except Exception as exc:
        print(f"  [внимание] captions.json не прочитан ({exc})")
        return None


def collect_images(root: Path, media_dir: Path) -> list[dict]:
    """Фото людей/карты: копируем файл в data/media/<topic>/, без OCR.

    Вектор строится по подписи (captions.json) либо по теме+имени файла.
    В payload кладётся относительный путь к изображению (поле image).
    """
    import shutil

    files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXT)
    documents: list[dict] = []
    for path in files:
        meta = guess_meta(path)
        caption = load_captions(path)
        text = caption or f"Иллюстрация по теме «{meta['topic']}»: {path.stem}"
        rel_dir = re.sub(r'[\\/:*?"<>|]', "_", meta["topic"])
        dest_dir = media_dir / rel_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / path.name
        shutil.copy2(path, dest)
        rel_path = f"{rel_dir}/{path.name}"
        documents.append(
            {
                "content": text,
                "source": path.name,
                "topic": meta["topic"],
                "doc_date": meta["doc_date"],
                "image": rel_path,
            }
        )
        print(f"  [img] {path.name} -> {rel_path} (подпись: {'captions' if caption else 'тема'})")
    return documents


def collect_documents(
    root: Path,
    *,
    chunk_size: int = 800,
    chunk_overlap: int = 150,
    limit: int | None = None,
) -> list[dict]:
    """Обходит каталог, извлекает текст, режет на чанки, валидирует метаданные."""
    files = sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED
        and not p.name.startswith("~$")
    )
    if limit:
        files = files[:limit]
    legacy = sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in LEGACY_DOC
        and not p.name.startswith("~$")
    )
    if legacy:
        print(f"  [внимание] .doc без конвертации ({len(legacy)}): " + ", ".join(p.name for p in legacy[:5]))
    if not files:
        return []

    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap, length_function=len
    )

    documents: list[dict] = []
    for path in files:
        try:
            source = extract_source(path)
            text = source.text.strip()
        except Exception as exc:
            print(f"  [пропуск, битый] {path.name} ({type(exc).__name__})")
            continue
        if not text:
            print(f"  [пропуск, пусто] {path.name}")
            continue
        meta = guess_meta(path)
        source_format = path.suffix.lower().lstrip(".")
        for i, chunk in enumerate(splitter.split_text(text)):
            documents.append(
                {
                    "content": chunk,
                    "source": f"{path.name}#{i + 1}",
                    "topic": meta["topic"],
                    "doc_date": meta["doc_date"],
                    "source_format": source_format,
                    "detected_format": source.detected_format,
                    "encoding": source.encoding,
                    "sha256": source.sha256,
                }
            )
        encoding_note = f", кодировка: {source.encoding}" if source.encoding else ""
        print(f"  [ok] {path.name}: {len(text)} символов (формат: {source.detected_format}{encoding_note})")
    return documents


def main() -> None:
    parser = argparse.ArgumentParser(description="Загрузка корпуса в Qdrant")
    parser.add_argument("--dir", default="history_database", help="Каталог с материалами")
    parser.add_argument("--limit", type=int, default=None, help="Максимум файлов (для пробы)")
    parser.add_argument("--chunk-size", type=int, default=800)
    parser.add_argument("--chunk-overlap", type=int, default=150)
    parser.add_argument("--host", default=None, help="Переопределить QDRANT_HOST")
    parser.add_argument("--port", type=int, default=None, help="Переопределить QDRANT_PORT")
    parser.add_argument("--collection", default=None, help="Переопределить QDRANT_COLLECTION")
    parser.add_argument("--images", action="store_true", help="Обработать изображения (jpg/png/webp): без OCR, файлы копируются в data/media")
    parser.add_argument("--media-dir", default=None, help="Каталог для изображений (по умолчанию MEDIA_DIR из настроек)")
    parser.add_argument("--dry-run", action="store_true", help="Только показать план загрузки")
    args = parser.parse_args()

    # Переопределения env — ДО импорта core.database (он читает env на импорте).
    if args.host:
        os.environ["QDRANT_HOST"] = args.host
    if args.port:
        os.environ["QDRANT_PORT"] = str(args.port)
    if args.collection:
        os.environ["QDRANT_COLLECTION"] = args.collection

    root = Path(args.dir)
    if not root.is_dir():
        sys.exit(f"Каталог не найден: {root}")

    if args.images:
        from app.config import Settings

        media_dir = Path(args.media_dir) if args.media_dir else Settings().media_dir
        documents = collect_images(root, media_dir)
        print(f"Подготовлено изображений: {len(documents)} (media: {media_dir})")
    else:
        documents = collect_documents(
            root, chunk_size=args.chunk_size, chunk_overlap=args.chunk_overlap, limit=args.limit
        )
        print(f"Подготовлено чанков: {len(documents)} из файлов в {root}")
    if args.dry_run:
        for d in documents[:5]:
            print(f"  - [{d['topic']}|{d['doc_date']}] {d['source']}: {d['content'][:80]}...")
        return
    if not documents:
        sys.exit("Нечего загружать.")

    from core.database import add_documents_to_store

    add_documents_to_store(documents)
    print("Готово.")


if __name__ == "__main__":
    main()
