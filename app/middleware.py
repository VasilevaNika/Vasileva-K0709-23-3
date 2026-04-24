"""
Middleware для инъекции UserRepository и FeedCache в хендлеры.
"""

from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.database import async_session_factory
from app.repository import UserRepository
from app.services.cache import FeedCache


class RepositoryMiddleware(BaseMiddleware):
    """
    Создаёт AsyncSession + UserRepository и передаёт их в хендлер как `repo`.
    """

    def __init__(self):
        pass

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        async with async_session_factory() as session:
            data["repo"] = UserRepository(session)
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise


class CacheMiddleware(BaseMiddleware):
    """
    Передаёт общий экземпляр FeedCache в хендлеры как `feed_cache`.
    """

    def __init__(self, cache: FeedCache):
        self._cache = cache

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        data["feed_cache"] = self._cache
        return await handler(event, data)
