import pytest

from english_tutor.config import load_config

BASE = {"BOT_TOKEN": "t", "GROQ_API_KEY": "g", "ADMIN_TELEGRAM_ID": "1"}


def test_loads_full_config():
    cfg = load_config({**BASE, "REMINDER_TIMES": "13:00,19:00", "TZ": "Europe/Kiev"})
    assert (cfg.bot_token, cfg.groq_api_key, cfg.admin_tg_id) == ("t", "g", 1)
    assert cfg.reminder_times == ["13:00", "19:00"] and cfg.tz == "Europe/Kiev"


def test_defaults():
    cfg = load_config(BASE)
    assert cfg.reminder_times == ["13:00", "19:00"] and cfg.tz == "Europe/Kiev"
    assert cfg.db_path == "tutor.db"


@pytest.mark.parametrize("missing", ["BOT_TOKEN", "GROQ_API_KEY", "ADMIN_TELEGRAM_ID"])
def test_missing_key_raises(missing):
    env = {k: v for k, v in BASE.items() if k != missing}
    with pytest.raises(ValueError, match=missing):
        load_config(env)
