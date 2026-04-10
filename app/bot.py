"""
Dating Telegram Bot — точка входа.

Запуск:
    python -m app.bot
    или
    BOT_TOKEN=xxx python -m app.bot
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import settings
from app.database import init_db
from app.handlers import register_main_router, register_registration_router
from app.middleware import RepositoryMiddleware


async def main():
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Инициализация БД
    await init_db()
    logging.info("Database initialized.")

    # Создание бота и диспетчера
    bot = Bot(token=settings.bot_token)
    storage = MemoryStorage()  # FSM-хранилище в памяти (можно заменить на Redis)
    dp = Dispatcher(storage=storage)

    # Middleware — инъекция репозитория
    dp.message.middleware(RepositoryMiddleware())
    dp.callback_query.middleware(RepositoryMiddleware())

    # Регистрация роутеров
    register_main_router(dp)
    register_registration_router(dp)

    logging.info("Bot is starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
