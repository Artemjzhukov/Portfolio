from english_tutor.services import material_exercises as me


def test_normalize_rejects_concatenated():
    assert me.normalize_for_match("end-to-end") != me.normalize_for_match("endtoend")
    assert me.check_pronunciation("end-to-end", "endtoend") is False

def test_normalize_hyphen_variant():
    assert me.normalize_for_match("end-to-end ownership") == me.normalize_for_match("end to end ownership")


def test_normalize_rejects_different():
    assert me.normalize_for_match("end to end ownership") != me.normalize_for_match("end to end leadership")


def test_check_pronunciation_hyphen():
    assert me.check_pronunciation("end-to-end ownership", "end to end ownership") is True


def test_check_spelling_exact():
    assert me.check_spelling("cat", "cat") is True
    assert me.check_spelling("cat", "dog") is False
