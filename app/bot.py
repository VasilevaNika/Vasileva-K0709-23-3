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
from app.handlers import (
    register_main_router,
    register_registration_router,
    register_feed_router,
    register_matches_router,
    register_profile_router,
)
from app.middleware import RepositoryMiddleware, CacheMiddleware
from app.services.cache import FeedCache, get_redis, close_redis


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Инициализация БД
    await init_db()
    logging.info("Database initialized.")

    # Redis и кэш
    redis = await get_redis()
    feed_cache = FeedCache(redis)
    logging.info("Redis connected.")

    # Бот и диспетчер
    bot = Bot(token=settings.bot_token)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Middleware
    repo_mw = RepositoryMiddleware()
    cache_mw = CacheMiddleware(feed_cache)

    dp.message.middleware(repo_mw)
    dp.callback_query.middleware(repo_mw)
    dp.message.middleware(cache_mw)
    dp.callback_query.middleware(cache_mw)

    # Регистрация роутеров (порядок важен: более специфичные — первыми)
    register_main_router(dp)
    register_registration_router(dp)
    register_feed_router(dp)
    register_matches_router(dp)
    register_profile_router(dp)

    logging.info("Bot is starting...")
    try:
        await dp.start_polling(bot)
    finally:
        await close_redis()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
