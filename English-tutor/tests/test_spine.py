import pytest

from english_tutor.services.spine import SPINE, topics


def test_all_levels_have_six_topics():
    for level in ("A2", "B1", "B2"):
        assert len(SPINE[level]) == 6


def test_topics_returns_copy_in_order():
    ts = topics("A2")
    assert ts == SPINE["A2"]
    ts.append("hack")
    assert len(SPINE["A2"]) == 6


def test_unknown_level_raises():
    with pytest.raises(KeyError):
        topics("C1")
