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
import os
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

SUPPORTED = {".txt", ".md", ".docx", ".pdf"}
_YEAR_RE = re.compile(r"(1[0-9]{3}|20[0-9]{2})")


def extract_text(path: Path) -> str:
    """Текст файла: txt/md напрямую, docx/pdf — через helpers из app/services/ocr."""
    suffix = path.suffix.lower()
    if suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".docx":
        from app.services.ocr import extract_docx_text

        return extract_docx_text(path.read_bytes())
    if suffix == ".pdf":
        from app.services.ocr import extract_pdf_pages

        return "\n".join(extract_pdf_pages(path.read_bytes()))
    raise ValueError(f"Неподдерживаемый формат: {path}")


def guess_meta(path: Path) -> dict:
    """topic — имя родительской папки или имя файла; doc_date — год из имени файла."""
    topic = path.parent.name if path.parent.name.lower() not in ("", ".") else path.stem
    match = _YEAR_RE.search(path.stem)
    return {"topic": topic, "doc_date": match.group(0) if match else None}


def collect_documents(
    root: Path,
    *,
    chunk_size: int = 800,
    chunk_overlap: int = 150,
    limit: int | None = None,
) -> list[dict]:
    """Обходит каталог, извлекает текст, режет на чанки, валидирует метаданные."""
    files = sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED
    )
    if limit:
        files = files[:limit]
    if not files:
        return []

    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap, length_function=len
    )

    documents: list[dict] = []
    for path in files:
        text = extract_text(path).strip()
        if not text:
            print(f"  [пропуск, пусто] {path.name}")
            continue
        meta = guess_meta(path)
        for i, chunk in enumerate(splitter.split_text(text)):
            documents.append(
                {
                    "content": chunk,
                    "source": f"{path.name}#{i + 1}",
                    "topic": meta["topic"],
                    "doc_date": meta["doc_date"],
                }
            )
        print(f"  [ok] {path.name}: {len(text)} символов")
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
