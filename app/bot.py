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
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import settings
from app.database import init_db
from app.handlers import (
    register_main_router,
    register_registration_router,
    register_feed_router,
    register_matches_router,
    register_profile_router,
    register_stats_router,
)
from app.middleware import RepositoryMiddleware, CacheMiddleware, StorageMiddleware, SwipeLimiterMiddleware
from app.services.cache import FeedCache, get_redis, close_redis
from app.services.storage import init_storage
from app.services.swipe_limit import SwipeLimiter


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
    swipe_limiter = SwipeLimiter(redis)
    logging.info("Redis connected.")

    # MinIO — объектное хранилище фотографий (опционально)
    minio_storage = await init_storage()

    # Бот и диспетчер
    session = AiohttpSession(proxy=settings.telegram_proxy) if settings.telegram_proxy else None
    bot = Bot(token=settings.bot_token, session=session)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Middleware
    repo_mw = RepositoryMiddleware()
    cache_mw = CacheMiddleware(feed_cache)
    storage_mw = StorageMiddleware(minio_storage)
    limiter_mw = SwipeLimiterMiddleware(swipe_limiter)

    dp.message.middleware(repo_mw)
    dp.callback_query.middleware(repo_mw)
    dp.message.middleware(cache_mw)
    dp.callback_query.middleware(cache_mw)
    dp.message.middleware(storage_mw)
    dp.callback_query.middleware(storage_mw)
    dp.message.middleware(limiter_mw)
    dp.callback_query.middleware(limiter_mw)

    # Регистрация роутеров (порядок важен: более специфичные — первыми)
    register_main_router(dp)
    register_registration_router(dp)
    register_feed_router(dp)
    register_matches_router(dp)
    register_profile_router(dp)
    register_stats_router(dp)

    logging.info("Bot is starting...")
    try:
        await dp.start_polling(bot)
    finally:
        await close_redis()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
