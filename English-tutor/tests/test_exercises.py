from english_tutor.services.exercises import check_answer, normalize


def test_normalize_strips_case_and_punctuation():
    assert normalize("  I'm  going home! ") == "i am going home"
    assert normalize("Went.") == "went"
    assert normalize("don't  STOP") == "do not stop"


def test_normalize_expands_contractions():
    # Both contracted and expanded forms should normalize to a canonical format
    assert normalize("I didn't know") == normalize("I did not know")
    assert normalize("She doesn't like it") == normalize("She does not like it")
    assert normalize("I'm ready") == normalize("I am ready")
    assert normalize("We've finished") == normalize("We have finished")
    assert normalize("They aren't here") == normalize("They are not here")


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


def test_check_smart_tolerance_full_sentence_for_gap():
    # If student types the whole sentence instead of just the missing word
    ex = {"type": "fill_in", "prompt": "I ___ to school yesterday.", "answer": "went"}
    assert check_answer(ex, "went") is True
    assert check_answer(ex, "I went to school yesterday.") is True
    assert check_answer(ex, "i went to school yesterday") is True
    assert check_answer(ex, "I go to school yesterday") is False


def test_check_smart_tolerance_with_parentheses_in_prompt():
    ex = {"type": "fill_in", "prompt": "She ___ (not / like) spicy food.", "answer": "didn't like"}
    assert check_answer(ex, "didn't like") is True
    assert check_answer(ex, "did not like") is True
    assert check_answer(ex, "She didn't like spicy food.") is True
    assert check_answer(ex, "She did not like spicy food") is True

