"""
Middleware для инъекции UserRepository в хендлеры.
"""

from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.repository import UserRepository


class RepositoryMiddleware(BaseMiddleware):
    """
    Middleware, который создаёт AsyncSession и UserRepository
    и передаёт их в хендлер как параметр `repo: UserRepository`.
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
