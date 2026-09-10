import pytest

from english_tutor.services import placement


def test_bank_has_20_ascending_questions():
    assert len(placement.QUESTIONS) == 20
    levels = [q["level"] for q in placement.QUESTIONS]
    assert levels.index("B1") > levels.index("A2") and levels.index("B2") > levels.index("B1")
    for q in placement.QUESTIONS:
        assert 0 <= q["answer"] < len(q["options"])


def test_score_written():
    answers = [q["answer"] for q in placement.QUESTIONS]
    assert placement.score_written(answers) == 20
    assert placement.score_written([None] * 20) == 0
    answers[0] = (answers[0] + 1) % 4
    assert placement.score_written(answers) == 19


def test_suggest_level_bands():
    assert placement.suggest_level(0) == "A2"
    assert placement.suggest_level(6) == "A2" and placement.suggest_level(11) == "A2"
    assert placement.suggest_level(12) == "B1" and placement.suggest_level(16) == "B1"
    assert placement.suggest_level(17) == "B2" and placement.suggest_level(20) == "B2"


def test_suggest_level_all_low_scores_map_to_a2():
    for score in range(0, 6):  # 0–5 were outside the old A2 band
        assert placement.suggest_level(score) == "A2"


def test_suggest_level_rejects_scores_below_zero():
    with pytest.raises(ValueError, match=r"0\.\.20"):
        placement.suggest_level(-1)


def test_suggest_level_rejects_scores_above_max():
    with pytest.raises(ValueError, match=r"0\.\.20"):
        placement.suggest_level(21)


def test_suggest_level_rejects_non_integer_score():
    with pytest.raises(ValueError):
        placement.suggest_level("12")


def test_voice_hint_moves_one_band_near_boundary():
    assert placement.suggest_level(11, "B1") == "B1"
    assert placement.suggest_level(12, "A2") == "A2"
    assert placement.suggest_level(13, "A2") == "B1"
    assert placement.suggest_level(16, "B2") == "B2"
    assert placement.suggest_level(10, "B2") == "A2"
    assert placement.suggest_level(14, None) == "B1"


def test_classify_voice():
    class L:
        def chat_json(self, system, user):
            return {"level": "A2"}

    assert placement.classify_voice("I go work every day", L()) == "A2"


def test_classify_voice_invalid_level_returns_none():
    class L:
        def chat_json(self, system, user):
            return {"level": "C1"}

    assert placement.classify_voice("hi", L()) is None


def test_classify_voice_llm_error_returns_none():
    class L:
        def chat_json(self, system, user):
            raise RuntimeError("boom")

    assert placement.classify_voice("hi", L()) is None
