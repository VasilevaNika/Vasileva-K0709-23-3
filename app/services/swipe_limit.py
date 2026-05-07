"""
Дневной лимит свайпов на базе Redis.

Ключ: swipe_limit:{user_id}:{YYYY-MM-DD}
TTL:  до полуночи текущего дня — автоматический сброс без cron.
"""

from datetime import date, datetime, timedelta

import redis.asyncio as aioredis

DAILY_SWIPE_LIMIT = 30


class SwipeLimiter:
    """Счётчик дневных свайпов пользователя."""

    def __init__(self, redis: aioredis.Redis):
        self._r = redis

    def _key(self, user_id: int) -> str:
        return f"swipe_limit:{user_id}:{date.today().isoformat()}"

    def _ttl_until_midnight(self) -> int:
        now = datetime.now()
        midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
        return max(1, int((midnight - now).total_seconds()))

    async def get_used(self, user_id: int) -> int:
        """Сколько свайпов использовано сегодня."""
        val = await self._r.get(self._key(user_id))
        return int(val) if val else 0

    async def increment(self, user_id: int) -> int:
        """Увеличить счётчик на 1, вернуть новое значение."""
        key = self._key(user_id)
        count = await self._r.incr(key)
        if count == 1:
            await self._r.expire(key, self._ttl_until_midnight())
        return count

    async def is_limit_reached(self, user_id: int) -> bool:
        """True если дневной лимит исчерпан."""
        return await self.get_used(user_id) >= DAILY_SWIPE_LIMIT

    async def remaining(self, user_id: int) -> int:
        """Сколько свайпов осталось до конца дня."""
        return max(0, DAILY_SWIPE_LIMIT - await self.get_used(user_id))
