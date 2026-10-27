# -*- coding: utf-8 -*-
"""Метрики извлечения по реальным файлам корпуса (по умолчанию — RTF).

Пишет markdown-таблицу: что за файл, какой формат определён по магии, какая
кодировка реально применена, сколько символов получилось и не осталось ли в
тексте RTF-разметки. Скрипт нужен, чтобы числа в отчёте воспроизводились одной
командой, а не пересказывались по памяти.

Использование (из папки history-rag):
    python scripts/report_legacy_formats.py --ext .rtf
    python scripts/report_legacy_formats.py --ext .rtf --out reports/ingestion_rtf_pilot.md
    python scripts/report_legacy_formats.py --ext .rtf --dump 3 --dump-dir reports/dumps
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.services.ocr import detect_file_type, parse_rtf_codepage  # noqa: E402
from scripts.upload_corpus import extract_source  # noqa: E402

# Если в извлечённом тексте остались эти последовательности — стриппер не сработал.
MARKUP_LEFTOVERS = ("\\rtf", "\\par", "\\'", "\\u-", "\\fonttbl")


def cyrillic_ratio(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    cyrillic = sum(1 for ch in letters if "\u0400" <= ch <= "\u04ff")
    return round(cyrillic / len(letters), 3)


def markup_leftovers(text: str) -> str:
    found = [mark for mark in MARKUP_LEFTOVERS if mark in text]
    return ", ".join(f"`{mark}`" for mark in found) if found else "—"


def main() -> None:
    parser = argparse.ArgumentParser(description="Метрики извлечения legacy-форматов")
    parser.add_argument("--dir", default="corpus_raw", help="Каталог с материалами")
    parser.add_argument("--ext", action="append", default=None, help="Расширение (можно повторять), по умолчанию .rtf")
    parser.add_argument("--out", default=None, help="Файл markdown-отчёта")
    parser.add_argument("--dump", type=int, default=0, help="Сколько файлов выгрузить в текстовом виде")
    parser.add_argument("--dump-dir", default=None, help="Каталог для выгрузок (нужен вместе с --dump)")
    args = parser.parse_args()

    root = Path(args.dir)
    if not root.is_dir():
        sys.exit(f"Каталог не найден: {root}")

    extensions = {ext.lower() for ext in (args.ext or [".rtf"])}
    files = sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in extensions and not path.name.startswith("~$")
    )
    if not files:
        sys.exit(f"Файлов {sorted(extensions)} не найдено в {root}")

    rows: list[dict] = []
    for path in files:
        raw = path.read_bytes()
        row = {
            "file": str(path.relative_to(root)).replace("\\", "/"),
            "bytes": len(raw),
            "detected": detect_file_type(raw[:8], path.name),
            "declared": parse_rtf_codepage(raw) or "—",
        }
        try:
            source = extract_source(path)
        except Exception as exc:  # ошибка извлечения не должна ломать отчёт
            rows.append({
                **row, "applied": "—", "chars": 0, "cyr": 0.0, "bad": 0,
                "leftovers": "—", "decision": f"skip_error ({type(exc).__name__})",
            })
            continue
        text = source.text.strip()
        rows.append({
            **row,
            "applied": source.encoding or "—",
            "chars": len(text),
            "cyr": cyrillic_ratio(text),
            "bad": text.count("\ufffd"),
            "leftovers": markup_leftovers(text),
            "decision": "load" if text else "skip_empty",
        })

    lines = [
        "| файл | байт | detected | \\ansicpg | применено | символов | доля кириллицы | U+FFFD | остатки разметки | решение |",
        "|---|---:|---|---|---|---:|---:|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| `{row['file']}` | {row['bytes']} | {row['detected']} | {row['declared']} | "
            f"{row['applied']} | {row['chars']} | {row['cyr']} | {row['bad']} | "
            f"{row['leftovers']} | {row['decision']} |"
        )

    loaded = [row for row in rows if row["decision"] == "load"]
    errors = [row for row in rows if row["decision"].startswith("skip_error")]
    empty = [row for row in rows if row["decision"] == "skip_empty"]
    mean_chars = round(sum(row["chars"] for row in rows) / len(rows))
    output = "\n".join(lines) + (
        f"\n\nВсего файлов: {len(rows)}; загружено: {len(loaded)}; пропущено (пусто): {len(empty)}; "
        f"ошибок: {len(errors)}; среднее символов на файл: {mean_chars}.\n"
    )
    print(output)

    if args.dump and args.dump_dir:
        dump_dir = Path(args.dump_dir)
        dump_dir.mkdir(parents=True, exist_ok=True)
        for row in loaded[: args.dump]:
            source_path = root / row["file"]
            text = extract_source(source_path).text
            target = dump_dir / (source_path.stem + ".txt")
            target.write_text(text, encoding="utf-8")
            print(f"[dump] {target} ({len(text)} символов)")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"[report] {out_path}")


if __name__ == "__main__":
    main()
