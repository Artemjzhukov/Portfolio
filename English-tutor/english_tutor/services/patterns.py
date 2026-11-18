"""Pattern Bank — canonical catalog of grammar patterns and functional sentence templates."""

from __future__ import annotations


class PatternID(str):
    """Stable identifier for a grammar pattern or functional template."""

    pass


# ---------------------------------------------------------------------------
# Grammar patterns
# ---------------------------------------------------------------------------

GRAMMAR_PATTERNS: dict[str, dict] = {
    "pat_001": {
        "name": "Present Simple vs Present Continuous",
        "category": "grammar",
        "cefr_level": "A2",
        "structure": "present simple vs am/is/are + verb-ing",
        "function": "Describing habits and facts vs temporary situations",
        "ru_explanation": "Настоящее простое (привычка) vs настоящее длительное (сейчас)",
        "english_examples": [
            "I work in IT.",
            "I am working on a new project this week.",
        ],
        "common_mistakes": [
            "Using the continuous form with stative verbs (I am knowing)",
            "Using the continuous form for permanent situations",
        ],
        "contrasting_pattern": "pat_002",
    },
    "pat_002": {
        "name": "Past Simple vs Present Perfect",
        "category": "grammar",
        "cefr_level": "B1",
        "structure": "verb-ed / irregular past vs have/has + past participle",
        "function": "Finished past events vs past events with present relevance",
        "ru_explanation": "Прошедшее простое (законченное) vs present perfect (результат важен сейчас)",
        "english_examples": [
            "I saw him yesterday.",
            "I have seen this dashboard before.",
        ],
        "common_mistakes": [
            "Using present perfect with a finished time marker (yesterday, last year)",
            "Using past simple when the result matters now",
        ],
        "contrasting_pattern": "pat_001",
    },
    "pat_003": {
        "name": "Present Perfect Continuous",
        "category": "grammar",
        "cefr_level": "B1",
        "structure": "have/has been + verb-ing",
        "function": "Duration of an activity leading up to now",
        "ru_explanation": "Действие длится и продолжается до сих пор",
        "english_examples": [
            "I have been working here for five years.",
            "She has been waiting for the bus for 20 minutes.",
        ],
        "common_mistakes": [
            "Using present perfect simple instead of the continuous form for duration",
            "Omitting have/has been",
        ],
        "contrasting_pattern": "pat_004",
    },
    "pat_004": {
        "name": "Past Perfect",
        "category": "grammar",
        "cefr_level": "B2",
        "structure": "had + past participle",
        "function": "An earlier past action before another past moment",
        "ru_explanation": "Действие, которое произошло раньше другого действия в прошлом",
        "english_examples": [
            "I had finished the report before the meeting started.",
            "She had never used this tool before.",
        ],
        "common_mistakes": [
            "Using past simple where the order of two past events matters",
            "Using have instead of had",
        ],
        "contrasting_pattern": "pat_003",
    },
    "pat_005": {
        "name": "Passive Voice",
        "category": "grammar",
        "cefr_level": "B2",
        "structure": "be + past participle",
        "function": "Focusing on the action or result rather than the doer",
        "ru_explanation": "Страдательный залог: важен результат, а не исполнитель",
        "english_examples": [
            "The feature was released last week.",
            "The meeting was postponed to Monday.",
        ],
        "common_mistakes": [
            "Omitting the be verb",
            "Using the wrong past participle form",
        ],
        "contrasting_pattern": None,
    },
    "pat_006": {
        "name": "Relative Clauses",
        "category": "grammar",
        "cefr_level": "B2",
        "structure": "who / which / that / where + clause",
        "function": "Adding descriptive information about a noun",
        "ru_explanation": "Определительное придаточное: who, which, that, where",
        "english_examples": [
            "The tool that we use every day is quite old.",
            "The colleague who helped me is on vacation.",
        ],
        "common_mistakes": [
            "Choosing the wrong relative pronoun",
            "Resuming the object twice (the book which I read it)",
        ],
        "contrasting_pattern": None,
    },
    "pat_007": {
        "name": "Conditionals (First Conditional)",
        "category": "grammar",
        "cefr_level": "B1",
        "structure": "if + present simple, will + bare infinitive",
        "function": "A realistic condition and its future result",
        "ru_explanation": "Реальное условие в будущем: if + present simple, will + глагол",
        "english_examples": [
            "If we finish on time, we will deploy today.",
            "If it rains, I will stay at home.",
        ],
        "common_mistakes": [
            "Using will in the if-clause",
            "Mixing the clause order incorrectly",
        ],
        "contrasting_pattern": "pat_008",
    },
    "pat_008": {
        "name": "Conditionals (Second Conditional)",
        "category": "grammar",
        "cefr_level": "B2",
        "structure": "if + past simple, would + bare infinitive",
        "function": "An unreal or hypothetical present/future condition",
        "ru_explanation": "Нереальное условие: if + past simple, would + глагол",
        "english_examples": [
            "If I had more time, I would learn Spanish.",
            "If I were the manager, I would change the process.",
        ],
        "common_mistakes": [
            "Using would in the if-clause",
            "Mixing first and second conditional forms",
        ],
        "contrasting_pattern": "pat_007",
    },
    "pat_009": {
        "name": "Modal Verbs",
        "category": "grammar",
        "cefr_level": "B2",
        "structure": "modal verb (must / should / could / might) + bare infinitive",
        "function": "Expressing obligation, advice, ability and possibility",
        "ru_explanation": "Модальные глаголы: долженствование, совет, возможность",
        "english_examples": [
            "You should restart the service first.",
            "It might be a caching problem.",
        ],
        "common_mistakes": [
            "Adding to after a modal verb (should to restart)",
            "Using must where should (advice) is meant",
        ],
        "contrasting_pattern": None,
    },
    "pat_010": {
        "name": "Gerund vs Infinitive",
        "category": "grammar",
        "cefr_level": "B2",
        "structure": "verb + -ing vs verb + to + infinitive",
        "function": "Choosing the correct verb form after another verb",
        "ru_explanation": "Герундий или инфинитив после глагола",
        "english_examples": [
            "I enjoy working with data.",
            "I want to improve my speaking.",
        ],
        "common_mistakes": [
            "Using to after verbs like enjoy, avoid, finish",
            "Changing the meaning with stop + -ing vs stop + to",
        ],
        "contrasting_pattern": None,
    },
}


# ---------------------------------------------------------------------------
# Functional sentence templates
# ---------------------------------------------------------------------------

FUNCTIONAL_TEMPLATES: dict[str, dict] = {
    "tpl_001": {
        "name": "Self-introduction",
        "category": "functional",
        "cefr_level": "A2",
        "structure": "I'm {name}, a {level} English learner from {country}.",
        "function": "Introducing yourself in a learning or professional context",
        "ru_explanation": "Представление себя",
        "english_template": (
            "I'm {name}, a {level} English learner from {country}. "
            "I want to practise {topic}."
        ),
        "slots": ["name", "level", "country", "topic"],
    },
    "tpl_002": {
        "name": "Professional experience description",
        "category": "functional",
        "cefr_level": "B1",
        "structure": "I have been {verb-ing} as a {role} for {duration}.",
        "function": "Describing professional experience and its duration",
        "ru_explanation": "Описание опыта работы",
        "english_template": "I have been {verb_ing} as a {role} for {duration}.",
        "slots": ["verb_ing", "role", "duration"],
    },
    "tpl_003": {
        "name": "Describing a challenge",
        "category": "functional",
        "cefr_level": "B1",
        "structure": "The main challenge was {issue}. I solved it by {action}.",
        "function": "Describing a difficulty and how it was resolved",
        "ru_explanation": "Описание проблемы и её решения",
        "english_template": "The main challenge was {issue}. I solved it by {action}.",
        "slots": ["issue", "action"],
    },
    "tpl_004": {
        "name": "Giving a reason",
        "category": "functional",
        "cefr_level": "B1",
        "structure": "The main reason was that {clause}.",
        "function": "Explaining why a decision or action was taken",
        "ru_explanation": "Объяснение причины",
        "english_template": "The main reason was that {clause}.",
        "slots": ["clause"],
    },
    "tpl_005": {
        "name": "Giving an opinion",
        "category": "functional",
        "cefr_level": "B2",
        "structure": "From my point of view, {opinion}.",
        "function": "Expressing a personal opinion",
        "ru_explanation": "Выражение мнения",
        "english_template": "From my point of view, {opinion}.",
        "slots": ["opinion"],
    },
    "tpl_006": {
        "name": "Describing results",
        "category": "functional",
        "cefr_level": "B2",
        "structure": "As a result, we managed to {result}.",
        "function": "Describing the outcome of an action or project",
        "ru_explanation": "Описание результата",
        "english_template": "As a result, we managed to {result}.",
        "slots": ["result"],
    },
    "tpl_007": {
        "name": "Comparison",
        "category": "functional",
        "cefr_level": "B2",
        "structure": "Compared to {reference}, {statement}.",
        "function": "Comparing two approaches, options or situations",
        "ru_explanation": "Сравнение двух вариантов",
        "english_template": "Compared to {reference}, {statement}.",
        "slots": ["reference", "statement"],
    },
    "tpl_008": {
        "name": "Agreeing with a reservation",
        "category": "functional",
        "cefr_level": "B2",
        "structure": "I agree that {point}, although {reservation}.",
        "function": "Partly agreeing while keeping a different position",
        "ru_explanation": "Частичное согласие с оговоркой",
        "english_template": "I agree that {point}, although {reservation}.",
        "slots": ["point", "reservation"],
    },
    "tpl_008b": {
        "name": "Time phrases with present perfect",
        "category": "functional",
        "cefr_level": "B1",
        "structure": "I have been {adjective} for {duration}.",
        "function": "Expressing how long a state or activity has lasted",
        "ru_explanation": "Сколько времени длится состояние или занятие",
        "english_template": "I have been {adjective} for {duration}.",
        "slots": ["adjective", "duration"],
    },
}

ALL_PATTERNS: dict[str, dict] = {**GRAMMAR_PATTERNS, **FUNCTIONAL_TEMPLATES}

# Human-friendly aliases accepted when the LLM or a caller uses a loose name.
_PATTERN_ALIASES: dict[str, str] = {
    "present_simple": "pat_001",
    "present_continuous": "pat_001",
    "past_simple": "pat_002",
    "present_perfect": "pat_002",
    "present_perfect_continuous": "pat_003",
    "past_perfect": "pat_004",
    "passive": "pat_005",
    "passive_voice": "pat_005",
    "relative_clause": "pat_006",
    "relative_clauses": "pat_006",
    "first_conditional": "pat_007",
    "second_conditional": "pat_008",
    "modal_verbs": "pat_009",
    "gerund_infinitive": "pat_010",
}


def get_pattern(pattern_id) -> dict | None:
    """Return the catalog entry for a stable pattern ID, or None if unknown."""
    if pattern_id is None:
        return None
    return ALL_PATTERNS.get(str(pattern_id).strip())


def list_patterns(
    category: str | None = None,
    ce_level: str | None = None,
    cefr_level: str | None = None,
) -> dict[str, dict]:
    """Return patterns filtered by category and/or CEFR level.

    ``cefr_level`` is accepted as an alias of ``ce_level`` so both spellings work.
    """
    level = cefr_level or ce_level
    result: dict[str, dict] = {}
    for pattern_id, pattern in ALL_PATTERNS.items():
        if category is not None and pattern.get("category") != category:
            continue
        if level is not None and pattern.get("cefr_level") != level:
            continue
        result[pattern_id] = pattern
    return result


def normalize_pattern_id(raw_id) -> PatternID | None:
    """Normalize a loose pattern reference into a stable PatternID.

    Accepts exact IDs (``pat_002``), loose names (``past simple``,
    ``Present-Perfect``) and known aliases. Returns ``None`` for unknown input so
    callers can skip it instead of inventing a pattern.
    """
    if not isinstance(raw_id, str):
        return None
    cleaned = raw_id.strip().lower().replace("-", " ").replace("_", " ")
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return None
    compact = cleaned.replace(" ", "_")
    if compact in ALL_PATTERNS:
        return PatternID(compact)
    alias = _PATTERN_ALIASES.get(compact)
    if alias is not None:
        return PatternID(alias)
    return None


def build_patterns_prompt(patterns, student_level: str | None = None) -> str:
    """Build a prompt segment describing the given patterns for the LLM.

    Unknown IDs and patterns whose CEFR level does not match ``student_level`` are
    skipped, so the prompt never describes a pattern outside the student's level.
    """
    lines: list[str] = []
    seen: set[str] = set()
    for raw in patterns or []:
        pattern_id = normalize_pattern_id(raw)
        if pattern_id is None or pattern_id in seen:
            continue
        pattern = ALL_PATTERNS[pattern_id]
        if student_level and pattern.get("cefr_level") != student_level:
            continue
        seen.add(pattern_id)
        description = (
            f"- {pattern_id} [{pattern['cefr_level']}] {pattern['name']}: "
            f"{pattern['function']}. RU: {pattern['ru_explanation']}."
        )
        examples = pattern.get("english_examples")
        if examples:
            description += " Examples: " + " | ".join(examples[:2])
        template = pattern.get("english_template")
        if template:
            slots = ", ".join(pattern.get("slots", []))
            description += f" Template: {template} (slots: {slots})"
        lines.append(description)
    return "\n".join(lines)


__all__ = [
    "ALL_PATTERNS",
    "FUNCTIONAL_TEMPLATES",
    "GRAMMAR_PATTERNS",
    "PatternID",
    "build_patterns_prompt",
    "get_pattern",
    "list_patterns",
    "normalize_pattern_id",
]
