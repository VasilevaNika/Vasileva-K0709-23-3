"""
Тесты FeedCache (app/services/cache.py).

Вместо реального Redis используется fakeredis — in-memory эмуляция
Redis API. Тесты не требуют запущенного Redis-сервера.
"""

import pytest
import pytest_asyncio

from fakeredis import aioredis as fakeredis_async

from app.services.cache import FeedCache, BATCH_SIZE


@pytest_asyncio.fixture
async def fake_redis():
    """Эмулятор Redis, изолированный для каждого теста."""
    r = fakeredis_async.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest_asyncio.fixture
def cache(fake_redis):
    return FeedCache(fake_redis)


# ─── Базовые операции ────────────────────────────────────────────────────────

class TestFeedCacheBasics:
    async def test_fill_and_get_next_returns_first(self, cache):
        await cache.fill(user_id=1, profile_ids=[10, 20, 30])
        first = await cache.get_next_profile_id(user_id=1)
        assert first == 10

    async def test_get_next_is_fifo(self, cache):
        await cache.fill(user_id=2, profile_ids=[100, 200, 300])

        results = []
        for _ in range(3):
            pid = await cache.get_next_profile_id(user_id=2)
            results.append(pid)

        assert results == [100, 200, 300]

    async def test_empty_cache_returns_none(self, cache):
        result = await cache.get_next_profile_id(user_id=999)
        assert result is None

    async def test_size_after_fill(self, cache):
        await cache.fill(user_id=3, profile_ids=[1, 2, 3, 4, 5])
        assert await cache.size(user_id=3) == 5

    async def test_size_decrements_after_pop(self, cache):
        await cache.fill(user_id=4, profile_ids=[1, 2, 3])

        await cache.get_next_profile_id(user_id=4)
        assert await cache.size(user_id=4) == 2

    async def test_size_returns_zero_for_unknown_user(self, cache):
        assert await cache.size(user_id=888) == 0


# ─── Перезапись и очистка ────────────────────────────────────────────────────

class TestFeedCacheFillOverwrite:
    async def test_fill_overwrites_previous_data(self, cache):
        await cache.fill(user_id=5, profile_ids=[100, 200, 300])
        await cache.fill(user_id=5, profile_ids=[1, 2])

        assert await cache.size(user_id=5) == 2
        first = await cache.get_next_profile_id(user_id=5)
        assert first == 1  # Новый список, не старый

    async def test_fill_with_empty_list_clears_cache(self, cache):
        await cache.fill(user_id=6, profile_ids=[1, 2, 3])
        await cache.fill(user_id=6, profile_ids=[])
        assert await cache.size(user_id=6) == 0

    async def test_clear_empties_cache(self, cache):
        await cache.fill(user_id=7, profile_ids=[1, 2, 3, 4])
        await cache.clear(user_id=7)
        assert await cache.size(user_id=7) == 0

    async def test_clear_on_empty_cache_does_not_raise(self, cache):
        await cache.clear(user_id=777)  # не должно бросить исключение


# ─── Изоляция между пользователями ──────────────────────────────────────────

class TestFeedCacheIsolation:
    async def test_different_users_have_independent_caches(self, cache):
        await cache.fill(user_id=10, profile_ids=[101, 102])
        await cache.fill(user_id=20, profile_ids=[201, 202, 203])

        assert await cache.size(user_id=10) == 2
        assert await cache.size(user_id=20) == 3

    async def test_pop_from_one_user_does_not_affect_another(self, cache):
        await cache.fill(user_id=11, profile_ids=[1, 2])
        await cache.fill(user_id=12, profile_ids=[3, 4])

        await cache.get_next_profile_id(user_id=11)

        assert await cache.size(user_id=11) == 1
        assert await cache.size(user_id=12) == 2  # не изменился


# ─── Константа BATCH_SIZE ────────────────────────────────────────────────────

class TestBatchSize:
    def test_batch_size_is_positive(self):
        assert BATCH_SIZE > 0

    async def test_cache_holds_batch_size_items(self, cache):
        ids = list(range(1, BATCH_SIZE + 1))
        await cache.fill(user_id=50, profile_ids=ids)
        assert await cache.size(user_id=50) == BATCH_SIZE
