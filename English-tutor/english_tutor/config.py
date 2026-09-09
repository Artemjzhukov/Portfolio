import os
from dataclasses import dataclass, field
from typing import Mapping


@dataclass
class Config:
    bot_token: str
    groq_api_key: str
    admin_tg_id: int
    db_path: str = "tutor.db"
    reminder_times: list[str] = field(default_factory=lambda: ["13:00", "19:00"])
    tz: str = "Europe/Kiev"


_REQUIRED = ("BOT_TOKEN", "GROQ_API_KEY", "ADMIN_TELEGRAM_ID")


def load_config(env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    for key in _REQUIRED:
        if not env.get(key):
            raise ValueError(f"Missing required env var: {key}")
    return Config(
        bot_token=env["BOT_TOKEN"],
        groq_api_key=env["GROQ_API_KEY"],
        admin_tg_id=int(env["ADMIN_TELEGRAM_ID"]),
        db_path=env.get("DB_PATH", "tutor.db"),
        reminder_times=env.get("REMINDER_TIMES", "13:00,19:00").split(","),
        tz=env.get("TZ", "Europe/Kiev"),
    )
