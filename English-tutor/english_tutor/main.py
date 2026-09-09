import asyncio
import os
from pathlib import Path

from english_tutor.bot import create_bot, create_dispatcher
from english_tutor.config import load_config
from english_tutor.db import connect
from english_tutor.llm.groq_service import GroqService


def load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


async def main() -> None:
    load_dotenv()
    config = load_config()
    conn = connect(config.db_path)
    llm = GroqService(api_key=config.groq_api_key)
    dp = create_dispatcher(config, conn, llm)
    bot = create_bot(config)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
