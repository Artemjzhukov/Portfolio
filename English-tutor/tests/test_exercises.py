from english_tutor.services.exercises import check_answer, normalize


def test_normalize_strips_case_and_punctuation():
    assert normalize("  I'm  going home! ") == "i'm going home"
    assert normalize("Went.") == "went"
    assert normalize("don't  STOP") == "don't stop"


def test_check_exact_match():
    ex = {"type": "fill_in", "prompt": "I ___ home.", "answer": "went"}
    assert check_answer(ex, "Went") is True
    assert check_answer(ex, "gone") is False


def test_check_accepted_alternatives():
    ex = {"type": "translate", "prompt": "Она работает тут.", "answer": "she works here",
          "accept": ["she is working here"]}
    assert check_answer(ex, "She works here.") is True
    assert check_answer(ex, "she is working here") is True
    assert check_answer(ex, "she work here") is False
