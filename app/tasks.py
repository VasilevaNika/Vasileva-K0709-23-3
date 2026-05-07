"""
Celery-задачи (tasks) для Dating Bot.

Все задачи работают в отдельном процессе (celery worker), поэтому они
синхронные. Внутри каждой задачи создаётся собственный event loop через
asyncio.run(), а для работы с БД — отдельный async-движок SQLAlchemy.
Это стандартный паттерн: async-первый бот + sync Celery worker.

Задачи:
  1. refresh_all_ratings   — периодический (раз в 10 мин через Celery Beat)
                             пересчитывает рейтинги ВСЕХ профилей в БД
  2. update_profile_rating — событийный, вызывается сразу после свайпа
                             пересчитывает рейтинг ОДНОГО конкретного профиля
"""

import asyncio
import logging

from celery import shared_task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models import Profile
from app.services.ranking import refresh_profile_rating

logger = logging.getLogger(__name__)


# ─── Вспомогательные функции ──────────────────────────────────────────────────

def _make_session_factory():
    """
    Создаёт свежий async-движок и фабрику сессий.
    Вызывается внутри asyncio.run(), чтобы движок принадлежал
    текущему event loop-у — это необходимо для asyncpg.
    """
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


# ─── Задача 1: Периодический пересчёт всех рейтингов ─────────────────────────

@shared_task(
    name="app.tasks.refresh_all_ratings",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def refresh_all_ratings(self):
    """
    Периодически пересчитывает рейтинги (primary, behavior, combined)
    для всех профилей и сохраняет в таблицу profile_ratings.

    Вызывается Celery Beat каждые 10 минут согласно расписанию в celery_app.py.
    Это «Рейтинг (фон)» из архитектурной схемы проекта.
    """
    try:
        updated = asyncio.run(_async_refresh_all_ratings())
        logger.info("refresh_all_ratings: обновлено %d профилей", updated)
        return {"updated": updated}
    except Exception as exc:
        logger.error("refresh_all_ratings завершилась с ошибкой: %s", exc)
        raise self.retry(exc=exc)


async def _async_refresh_all_ratings() -> int:
    engine, factory = _make_session_factory()
    try:
        async with factory() as session:
            result = await session.execute(select(Profile))
            profiles = list(result.scalars().all())

            for profile in profiles:
                await refresh_profile_rating(session, profile)

            await session.commit()
        return len(profiles)
    finally:
        await engine.dispose()


# ─── Задача 2: Пересчёт рейтинга одного профиля после свайпа ─────────────────

@shared_task(
    name="app.tasks.update_profile_rating",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def update_profile_rating(self, profile_id: int):
    """
    Пересчитывает рейтинг конкретного профиля сразу после свайпа.
    Вызывается из handlers/feed.py через .delay() — асинхронно, не блокируя бота.

    Почему это нужно: поведенческий рейтинг (behavior_score) зависит от числа
    лайков и мэтчей, которые изменяются при каждом свайпе. Без обновления
    рейтинг в profile_ratings устаревал бы до следующего планового пересчёта.
    """
    try:
        asyncio.run(_async_update_profile_rating(profile_id))
        logger.info("update_profile_rating: профиль %d обновлён", profile_id)
    except Exception as exc:
        logger.error("update_profile_rating(%d) завершилась с ошибкой: %s", profile_id, exc)
        raise self.retry(exc=exc)


async def _async_update_profile_rating(profile_id: int) -> None:
    engine, factory = _make_session_factory()
    try:
        async with factory() as session:
            profile = await session.get(Profile, profile_id)
            if profile is None:
                logger.warning("update_profile_rating: профиль %d не найден", profile_id)
                return
            await refresh_profile_rating(session, profile)
            await session.commit()
    finally:
        await engine.dispose()
