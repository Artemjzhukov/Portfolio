from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from english_tutor.handlers import admin, lessons, registration


def create_dispatcher(config, conn, llm) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin.router)
    dp.include_router(registration.router)
    dp.include_router(lessons.router)
    dp.workflow_data.update(conn=conn, llm=llm, admin_id=config.admin_tg_id)
    return dp


def create_bot(config) -> Bot:
    return Bot(token=config.bot_token)
