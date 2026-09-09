import pytest

from english_tutor.services import limits


def test_text_ok():
    assert limits.check_text("привет") is None


def test_text_too_long():
    err = limits.check_text("a" * (limits.MAX_TEXT_CHARS + 1))
    assert err is not None and "символ" in err


def test_theme_ok():
    assert limits.check_theme("cooking") is None


def test_theme_too_long():
    assert limits.check_theme("a" * (limits.MAX_THEME_CHARS + 1)) is not None


def test_voice_ok():
    voice = type("V", (), {"duration": 30})()
    assert limits.check_voice(voice) is None


def test_voice_too_long():
    voice = type("V", (), {"duration": limits.MAX_VOICE_SECONDS + 1})()
    assert limits.check_voice(voice) is not None


def test_voice_missing_duration_is_ok():
    voice = type("V", (), {})()  # no duration attr
    assert limits.check_voice(voice) is None


def test_daily_quota_counts_up(conn):
    db = pytest.importorskip("english_tutor.db")
    assert limits.daily_left(conn, 1) == limits.DAILY_LLM_LIMIT
    limits.register_llm_call(conn, 1)
    limits.register_llm_call(conn, 1)
    assert limits.daily_left(conn, 1) == limits.DAILY_LLM_LIMIT - 2


def test_daily_quota_resets_next_day(conn):
    from datetime import date, timedelta
    from english_tutor import db

    limits.register_llm_call(conn, 1)
    db.bump_usage(conn, 1, day=str(date.today() - timedelta(days=1)))
    assert limits.daily_left(conn, 1) == limits.DAILY_LLM_LIMIT - 1


def test_daily_quota_enforced(conn):
    for _ in range(limits.DAILY_LLM_LIMIT):
        limits.register_llm_call(conn, 1)
    assert limits.daily_left(conn, 1) == 0
    assert limits.can_use_llm(conn, 1) is False
