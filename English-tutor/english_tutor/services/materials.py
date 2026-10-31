import hashlib
import json
import re

from english_tutor.llm.prompts import MATERIAL_ANALYSIS_SYSTEM_PROMPT


class MaterialFormatError(Exception):
    pass


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def hash_text(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def _validate_items(items, name):
    if not isinstance(items, list):
        raise MaterialFormatError(f"{name} must be a list")
    if len(items) > 10:
        raise MaterialFormatError(f"{name} must have at most 10 items")
    out = []
    for it in items:
        if not isinstance(it, dict) or set(it) != {"en", "ru"}:
            raise MaterialFormatError(f"bad {name} entry: {it}")
        if not all(isinstance(v, str) and v.strip() for v in it.values()):
            raise MaterialFormatError(f"bad {name} values: {it}")
        out.append({"en": it["en"].strip(), "ru": it["ru"].strip()})
    return out


def parse_material_analysis(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise MaterialFormatError("analysis must be a JSON object")
    if "title" not in raw:
        raise MaterialFormatError("missing key: title")
    if not isinstance(raw["title"], str) or not raw["title"].strip():
        raise MaterialFormatError("title must be a non-empty string")
    phrases = _validate_items(raw.get("phrases", []), "phrases")
    terms = _validate_items(raw.get("terms", []), "terms")
    words = _validate_items(raw.get("words", []), "words")
    return {"title": raw["title"].strip(), "phrases": phrases, "terms": terms, "words": words}


def build_prompt(text: str) -> tuple[str, str]:
    return MATERIAL_ANALYSIS_SYSTEM_PROMPT, f"Analyze this text:\n{text}"


async def get_or_analyze_material(conn, llm, student_id, text, level=None):
    from english_tutor import db

    norm = normalize_text(text)
    h = hash_text(norm)
    cached = db.get_material_by_hash(conn, student_id, h)
    if cached is not None:
        analysis = json.loads(cached["analysis_json"])
        return cached, analysis, True
    system, user = build_prompt(norm)
    if level:
        user = f"Learner CEFR level: {level}.\n" + user
    if hasattr(llm, "chat_json_async"):
        raw = await llm.chat_json_async(system, user)
    else:
        import asyncio

        raw = await asyncio.to_thread(llm.chat_json, system, user)
    analysis = parse_material_analysis(raw)
    title = analysis["title"]
    material_id = db.save_material(
        conn, student_id, h, norm, title, json.dumps(analysis, ensure_ascii=False)
    )
    items = []
    for t in ("phrase", "term", "word"):
        key = {"phrase": "phrases", "term": "terms", "word": "words"}[t]
        for it in analysis[key]:
            items.append({"type": t, "en": it["en"], "ru": it["ru"]})
    db.save_material_items(conn, material_id, items)
    material = db.get_material(conn, material_id)
    return material, analysis, False


def format_analysis(material, analysis) -> str:
    lines = [f"📄 {analysis['title']}", ""]
    for section, key in (("Фразы", "phrases"), ("Термины", "terms"), ("Слова", "words")):
        items = analysis[key]
        if not items:
            continue
        lines.append(f"{section}:")
        for i, it in enumerate(items, 1):
            lines.append(f"{i}. {it['en']} — {it['ru']}")
        lines.append("")
    lines.append("Выбери, что сохранить в повторение (кнопки ниже).")
    return "\n".join(lines)
