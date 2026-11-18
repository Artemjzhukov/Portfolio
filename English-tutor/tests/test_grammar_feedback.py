import pytest

from english_tutor import db
from english_tutor.handlers import lessons as lessons_h
from english_tutor.services import grammar_feedback as gf
from english_tutor.services import limits
from english_tutor.services.patterns import (
    FUNCTIONAL_TEMPLATES,
    GRAMMAR_PATTERNS,
    build_patterns_prompt,
    get_pattern,
    list_patterns,
    normalize_pattern_id,
)


class FakeLLM:
    """Minimal LLM double exposing chat_json_async like GroqService."""

    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    async def chat_json_async(self, system, user):
        self.calls.append((system, user))
        if self.error is not None:
            raise self.error
        return self.payload


class SyncLLM:
    """LLM double without async API, to exercise the to_thread fallback."""

    def __init__(self, payload):
        self.payload = payload

    def chat_json(self, system, user):
        return self.payload


# ---------------------------------------------------------------------------
# Pattern Bank
# ---------------------------------------------------------------------------


def test_catalog_sizes_and_structure():
    assert len(GRAMMAR_PATTERNS) == 10
    assert len(FUNCTIONAL_TEMPLATES) == 9
    all_ids = list(GRAMMAR_PATTERNS) + list(FUNCTIONAL_TEMPLATES)
    assert len(all_ids) == len(set(all_ids))

    for pattern in GRAMMAR_PATTERNS.values():
        assert pattern["category"] == "grammar"
        assert pattern["cefr_level"] in {"A1", "A2", "B1", "B2", "C1"}
        assert pattern["ru_explanation"]
        assert pattern["english_examples"]

    for pattern in FUNCTIONAL_TEMPLATES.values():
        assert pattern["category"] == "functional"
        assert pattern["cefr_level"] in {"A1", "A2", "B1", "B2", "C1"}
        assert pattern["english_template"]
        assert pattern["slots"]


def test_get_and_list_patterns():
    assert get_pattern("pat_002")["name"].startswith("Past Simple")
    assert get_pattern("nope") is None
    assert get_pattern(None) is None

    assert set(list_patterns(ce_level="A2")) == {"pat_001", "tpl_001"}
    assert set(list_patterns(cefr_level="A2")) == {"pat_001", "tpl_001"}
    assert set(list_patterns(category="functional")) == set(FUNCTIONAL_TEMPLATES)
    assert list_patterns(category="grammar", ce_level="C1") == {}


def test_normalize_pattern_id():
    assert normalize_pattern_id("pat_003") == "pat_003"
    assert normalize_pattern_id("Past Simple") == "pat_002"
    assert normalize_pattern_id("present-perfect") == "pat_002"
    assert normalize_pattern_id("  ") is None
    assert normalize_pattern_id("made_up_pattern") is None
    assert normalize_pattern_id(None) is None


def test_build_patterns_prompt_skips_unknown_and_wrong_level():
    prompt = build_patterns_prompt(["pat_001", "pat_004", "nope"], "A2")
    assert "pat_001" in prompt
    assert "pat_004" not in prompt
    assert "nope" not in prompt
    assert build_patterns_prompt(["pat_004"], "A2") == ""
    assert build_patterns_prompt(None, "B2") == ""


# ---------------------------------------------------------------------------
# analyze_grammar
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_grammar_happy_path():
    llm = FakeLLM(
        {
            "status": "analyzed",
            "overall_message": "Почти хорошо",
            "corrections": [
                {
                    "original": "I go there yesterday",
                    "corrected": "I went there yesterday",
                    "explanation_ru": "нужно прошедшее время",
                    "pattern_id": "past_simple",
                    "confidence": 0.9,
                }
            ],
            "correct_patterns": ["pat_001", "not_a_pattern"],
            "natural_version": "I went there yesterday.",
            "naturalness_note_ru": "звучит естественно",
        }
    )
    result = await gf.analyze_grammar(
        "I go there yesterday with my team",
        llm,
        task_description="tell about yesterday",
        student_level="B1",
        pattern_ids=["pat_002"],
    )

    assert result["status"] == gf.STATUS_ANALYZED
    assert result["overall_message"] == "Почти хорошо"
    assert result["corrections"][0]["pattern_id"] == "pat_002"
    assert result["corrections"][0]["confidence"] == 0.9
    assert result["correct_patterns"] == ["pat_001"]
    assert result["natural_version"] == "I went there yesterday."
    assert result["naturalness_note_ru"] == "звучит естественно"
    assert result["transcript"] == "I go there yesterday with my team"
    # Pattern context reached the prompt.
    assert "pat_002" in llm.calls[0][1]


@pytest.mark.asyncio
async def test_analyze_grammar_drops_malformed_corrections():
    llm = FakeLLM(
        {
            "corrections": [
                "oops",
                {"original": "", "corrected": "x"},
                {"original": "same", "corrected": "same"},
                {
                    "original": "I has",
                    "corrected": "I have",
                    "confidence": "high",
                    "pattern_id": "banana",
                },
                {"original": "He go", "corrected": "He goes", "confidence": 7},
            ],
            "overall_message": "",
        }
    )
    result = await gf.analyze_grammar("I has a question about the task", llm)

    assert result["status"] == gf.STATUS_ANALYZED
    assert len(result["corrections"]) == 2
    assert result["corrections"][0]["confidence"] is None
    assert result["corrections"][0]["pattern_id"] is None
    assert result["corrections"][1]["confidence"] == 1.0
    assert result["overall_message"]


@pytest.mark.asyncio
async def test_analyze_grammar_natural_version_equal_to_transcript_is_dropped():
    llm = FakeLLM(
        {
            "corrections": [],
            "natural_version": "I work with data every day",
        }
    )
    result = await gf.analyze_grammar("I work with data every day", llm)
    assert result["status"] == gf.STATUS_ANALYZED
    assert result["natural_version"] is None


@pytest.mark.asyncio
async def test_analyze_grammar_sync_llm_fallback():
    result = await gf.analyze_grammar(
        "I want to improve my English", SyncLLM({"corrections": []})
    )
    assert result["status"] == gf.STATUS_ANALYZED


@pytest.mark.asyncio
async def test_analyze_grammar_llm_error_preserves_transcript():
    llm = FakeLLM(error=RuntimeError("groq is down"))
    transcript = "I have been working here for many years"
    result = await gf.analyze_grammar(transcript, llm)

    assert result["status"] == gf.STATUS_LLM_ERROR
    assert result["transcript"] == transcript
    assert result["corrections"] == []
    text = gf.format_feedback(result)
    assert "недоступен" in text
    assert "правильн" not in text.lower()


@pytest.mark.asyncio
async def test_analyze_grammar_malformed_payload():
    result = await gf.analyze_grammar(
        "This answer is long enough", FakeLLM(["not", "a", "dict"])
    )
    assert result["status"] == gf.STATUS_LLM_ERROR
    assert result["transcript"] == "This answer is long enough"


@pytest.mark.asyncio
async def test_analyze_grammar_unknown_status_is_error():
    result = await gf.analyze_grammar(
        "This answer is long enough", FakeLLM({"status": "everything_is_fine"})
    )
    assert result["status"] == gf.STATUS_LLM_ERROR
    assert result["corrections"] == []


@pytest.mark.asyncio
async def test_analyze_grammar_honours_insufficient_context_from_llm():
    llm = FakeLLM({"status": "insufficient_context", "overall_message": "Слишком шумно"})
    result = await gf.analyze_grammar("Mumble mumble something", llm)
    assert result["status"] == gf.STATUS_INSUFFICIENT_CONTEXT
    assert result["overall_message"] == "Слишком шумно"


@pytest.mark.asyncio
async def test_analyze_grammar_short_transcript_skips_llm():
    llm = FakeLLM({"corrections": []})
    result = await gf.analyze_grammar("Yes", llm)

    assert result["status"] == gf.STATUS_INSUFFICIENT_CONTEXT
    assert llm.calls == []
    text = gf.format_feedback(result)
    assert "правильн" not in text.lower()


@pytest.mark.asyncio
async def test_analyze_grammar_empty_transcript_skips_llm():
    llm = FakeLLM({"corrections": []})
    result = await gf.analyze_grammar("   ", llm)
    assert result["status"] == gf.STATUS_INSUFFICIENT_CONTEXT
    assert llm.calls == []


@pytest.mark.asyncio
async def test_analyze_grammar_without_llm_is_unavailable():
    result = await gf.analyze_grammar("I like this approach very much", None)
    assert result["status"] == gf.STATUS_UNAVAILABLE
    assert result["corrections"] == []


def test_format_feedback_renders_analysis():
    text = gf.format_feedback(
        {
            "status": gf.STATUS_ANALYZED,
            "overall_message": "Итог",
            "corrections": [
                {
                    "original": "I has",
                    "corrected": "I have",
                    "explanation_ru": "3-е лицо",
                    "pattern_id": "pat_002",
                    "confidence": 0.9,
                }
            ],
            "natural_version": "I have a question.",
            "naturalness_note_ru": "стиль в порядке",
        }
    )
    assert "«I has» → «I have»" in text
    assert "3-е лицо" in text
    assert "Итог" in text
    assert "Естественнее" in text
    assert "стиль в порядке" in text
    assert gf.format_feedback(None) is None


# ---------------------------------------------------------------------------
# lesson_voice_task integration
# ---------------------------------------------------------------------------


class FakeMessage:
    def __init__(self, text=None, tg_id=42, voice=None):
        self.text = text
        self.voice = voice
        self.from_user = type("U", (), {"id": tg_id})()
        self.sent = []
        self.bot = self

    async def answer(self, text, **kw):
        self.sent.append(text)


class FakeState:
    def __init__(self):
        self.state, self.data = None, {}

    async def set_state(self, s):
        self.state = s

    async def update_data(self, **kw):
        self.data.update(kw)

    async def get_data(self):
        return dict(self.data)

    async def clear(self):
        self.state, self.data = None, {}


def _lesson():
    return {
        "title": "T",
        "explanation_ru": "e",
        "exercises": [
            {
                "type": "translate",
                "instruction_ru": "i",
                "prompt": "p",
                "answer": "a",
                "hint_ru": "h",
            }
        ],
        "voice_task": "tell me about your day",
        "vocab": [{"en": "chunk", "ru": "чанк"}],
    }


def _set_quota(conn, used):
    conn.execute(
        "INSERT INTO daily_usage (student_id, day, llm_calls) VALUES (?, ?, ?)",
        (42, limits._today(), used),
    )
    conn.commit()


async def _start_task(conn, st, monkeypatch, transcript):
    db.upsert_student(conn, 42, status="active", level="B2")
    import english_tutor.handlers.voice as voice_mod

    async def fake_transcribe(message, bot, llm):
        return transcript

    monkeypatch.setattr(voice_mod, "save_and_transcribe", fake_transcribe)
    st.state = lessons_h.LessonSession.voice_task
    await st.update_data(
        lesson=_lesson(),
        meta={"kind": "curriculum", "level": "B2", "topic": "t", "student_id": None},
        voice_task="tell me about your day",
    )
    return FakeMessage(voice=type("V", (), {"duration": 5})())


@pytest.mark.asyncio
async def test_lesson_voice_task_reports_grammar_feedback(conn, monkeypatch):
    llm = FakeLLM(
        {
            "status": "analyzed",
            "overall_message": "Есть одна ошибка",
            "corrections": [
                {
                    "original": "I go to the gym yesterday",
                    "corrected": "I went to the gym yesterday",
                    "explanation_ru": "нужно прошедшее время",
                    "pattern_id": "pat_002",
                    "confidence": 0.9,
                }
            ],
            "correct_patterns": [],
        }
    )
    st = FakeState()
    msg = await _start_task(conn, st, monkeypatch, "I go to the gym yesterday")

    await lessons_h.lesson_voice_task(msg, st, conn, llm=llm)

    joined = "\n".join(msg.sent)
    assert "Расшифровка" in joined
    assert "Грамматический разбор" in joined
    assert "I went to the gym yesterday" in joined
    assert "Задание завершено" in joined
    assert st.state is None
    # Whisper call + analysis call were reserved separately.
    assert limits.daily_left(conn, 42) == limits.DAILY_LLM_LIMIT - 2


@pytest.mark.asyncio
async def test_lesson_voice_task_skips_feedback_when_quota_is_gone(conn, monkeypatch):
    _set_quota(conn, limits.DAILY_LLM_LIMIT - 1)
    llm = FakeLLM({"status": "analyzed", "corrections": []})
    st = FakeState()
    msg = await _start_task(conn, st, monkeypatch, "I go to the gym yesterday")

    await lessons_h.lesson_voice_task(msg, st, conn, llm=llm)

    joined = "\n".join(msg.sent)
    assert "Расшифровка" in joined
    assert "Разбор" not in joined
    assert llm.calls == []
    assert "Задание завершено" in joined
    assert st.state is None
    assert limits.daily_left(conn, 42) == 0


@pytest.mark.asyncio
async def test_lesson_voice_task_blocks_when_whisper_quota_is_gone(conn, monkeypatch):
    db.upsert_student(conn, 42, status="active", level="B2")
    _set_quota(conn, limits.DAILY_LLM_LIMIT)
    calls = {"n": 0}

    async def fake_transcribe(message, bot, llm):
        calls["n"] += 1
        return "I go to the gym yesterday"

    import english_tutor.handlers.voice as voice_mod

    monkeypatch.setattr(voice_mod, "save_and_transcribe", fake_transcribe)
    st = FakeState()
    st.state = lessons_h.LessonSession.voice_task
    await st.update_data(
        lesson=_lesson(),
        meta={"kind": "curriculum", "level": "B2", "topic": "t", "student_id": None},
        voice_task="tell me about your day",
    )
    msg = FakeMessage(voice=type("V", (), {"duration": 5})())

    await lessons_h.lesson_voice_task(msg, st, conn, llm=FakeLLM({"corrections": []}))

    joined = "\n".join(msg.sent)
    assert "Дневной лимит" in joined
    assert calls["n"] == 0
    assert st.state == lessons_h.LessonSession.voice_task


@pytest.mark.asyncio
async def test_lesson_voice_task_llm_error_still_completes(conn, monkeypatch):
    llm = FakeLLM(error=RuntimeError("groq is down"))
    st = FakeState()
    msg = await _start_task(conn, st, monkeypatch, "I go to the gym yesterday")

    await lessons_h.lesson_voice_task(msg, st, conn, llm=llm)

    joined = "\n".join(msg.sent)
    assert "Расшифровка" in joined
    assert "недоступен" in joined
    assert "Задание завершено" in joined
    assert "правильн" not in joined.lower()
    assert st.state is None


@pytest.mark.asyncio
async def test_lesson_voice_task_does_not_analyse_empty_transcript(conn, monkeypatch):
    llm = FakeLLM({"corrections": []})
    st = FakeState()
    msg = await _start_task(conn, st, monkeypatch, "   ")

    await lessons_h.lesson_voice_task(msg, st, conn, llm=llm)

    joined = "\n".join(msg.sent)
    assert "Не расслышал" in joined
    assert llm.calls == []
    assert st.state == lessons_h.LessonSession.voice_task


@pytest.mark.asyncio
async def test_lesson_voice_task_short_answer_does_not_spend_extra_quota(conn, monkeypatch):
    llm = FakeLLM({"corrections": []})
    st = FakeState()
    msg = await _start_task(conn, st, monkeypatch, "Yes")

    await lessons_h.lesson_voice_task(msg, st, conn, llm=llm)

    joined = "\n".join(msg.sent)
    assert "слишком короткий" in joined.lower()
    assert llm.calls == []
    assert "Задание завершено" in joined
    assert st.state is None
    # Only the Whisper call was charged; the analysis never reached the LLM.
    assert limits.daily_left(conn, 42) == limits.DAILY_LLM_LIMIT - 1


