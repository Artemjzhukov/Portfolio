from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from english_tutor.handlers import admin, errors, lessons, registration, review


def create_dispatcher(config, conn, llm) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin.router)
    dp.include_router(registration.router)
    dp.include_router(lessons.router)
    dp.include_router(review.router)
    dp.include_router(errors.router)
    dp.workflow_data.update(conn=conn, llm=llm, admin_id=config.admin_tg_id)
    return dp


def create_bot(config) -> Bot:
    return Bot(token=config.bot_token)
