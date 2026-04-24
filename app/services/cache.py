"""
Redis-кэш для пачек отранжированных анкет.

Логика:
- При старте сессии для пользователя запрашивается ранжированный список анкет.
- Первая анкета показывается сразу, остальные 9 кэшируются в Redis.
- На последней из 10 список обновляется автоматически.
- TTL кэша — 10 минут (пользователь мог уйти, список устарел).
"""

import json
import logging
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

FEED_KEY = "feed:{user_id}"
FEED_TTL = 600  # секунд
BATCH_SIZE = 10


class FeedCache:
    """Кэш ленты анкет на базе Redis."""

    def __init__(self, redis: aioredis.Redis):
        self._r = redis

    def _key(self, user_id: int) -> str:
        return FEED_KEY.format(user_id=user_id)

    async def get_next_profile_id(self, user_id: int) -> Optional[int]:
        """Взять следующий profile_id из кэша. None если пусто."""
        key = self._key(user_id)
        raw = await self._r.lpop(key)
        if raw is None:
            return None
        return int(raw)

    async def fill(self, user_id: int, profile_ids: list[int]) -> None:
        """Заполнить кэш списком profile_ids (перезаписать)."""
        key = self._key(user_id)
        await self._r.delete(key)
        if profile_ids:
            await self._r.rpush(key, *[str(pid) for pid in profile_ids])
            await self._r.expire(key, FEED_TTL)
        logger.debug("Feed cache filled for user %s: %d profiles", user_id, len(profile_ids))

    async def size(self, user_id: int) -> int:
        """Количество оставшихся анкет в кэше."""
        return await self._r.llen(self._key(user_id))

    async def clear(self, user_id: int) -> None:
        await self._r.delete(self._key(user_id))


_redis_client: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
