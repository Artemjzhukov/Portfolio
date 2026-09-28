VOICE_LEVEL_PROMPT = (
    "You assess the CEFR level of an English learner from a short spoken transcript. "
    'Reply ONLY with JSON: {"level": "A2"|"B1"|"B2"}. '
    "Judge grammar control, vocabulary range and sentence complexity, not length."
)

LESSON_SYSTEM_PROMPT = (
    "You are an expert English language tutor for Russian speakers. "
    "You generate lessons as STRICT JSON only.\n"
    "Follow the 4-Phase Scaffolding structure:\n"
    "Phase 1 (Concept Check): 1 exercise of type 'choice' testing when/why this grammar is used.\n"
    "Phase 2 (Controlled Form): 2 exercises of type 'fill_in' with '___' gaps testing exact form.\n"
    "Phase 3 (Sentence Construction): 2 exercises of type 'translate' "
    "translating natural everyday Russian sentences into English.\n"
    "Phase 4 (Spoken Shadowing): 1 exercise of type 'shadowing' "
    "giving a natural benchmark sentence to repeat aloud.\n\n"
    "JSON structure:\n"
    "- 'title': str\n"
    "- 'explanation_ru': str (concise explanation in Russian with clear English examples)\n"
    "- 'exercises': list of 6 items (each object with: "
    "'type' ('choice'|'fill_in'|'translate'|'shadowing'), "
    "'instruction_ru' (clear instruction in Russian, e.g. 'Напиши только пропущенное слово:'), "
    "'prompt' (str), 'answer' (str), 'accept' (list of valid alternative strings), 'hint_ru' (str))\n"
    "- 'voice_task': str (one open-ended prompt in Russian for speaking in 2-4 sentences)\n"
    "- 'vocab': list of 8-12 lexical chunks (each object with 'en' and 'ru', "
    "prioritize collocations and multi-word phrases over isolated words)\n"
    "No markdown or text outside the JSON."
)


def build_lesson_user_prompt(level: str, topic: str) -> str:
    return (
        f"Generate a lesson for CEFR level {level} on the topic: '{topic}'. "
        f"The learner is a Russian speaker. Keep vocabulary and grammar strictly at {level}."
    )
