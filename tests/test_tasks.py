"""
Тесты Celery-задач (app/tasks.py).

Задачи — синхронные обёртки вокруг async-функций. Тестируем:
1. Регистрацию задач в Celery-приложении.
2. Логику async-хелперов (_async_*) напрямую, подменяя фабрику
   сессий на тестовую через unittest.mock.patch.

asyncio.run() внутри Celery-задач в тестах не вызываем, чтобы
не создавать вложенных event loop-ов (pytest-asyncio уже управляет loop-ом).
"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models import ProfileRating
from app.repository import UserRepository


# ─── Вспомогательный контекстный менеджер ────────────────────────────────────

class _FakeSessionFactory:
    """
    Подменяет async_sessionmaker: при вызове () возвращает
    async context manager, который отдаёт переданную session.
    """

    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        pass


def _make_mock_engine():
    engine = AsyncMock()
    engine.dispose = AsyncMock()
    return engine


# ─── Регистрация задач в Celery ───────────────────────────────────────────────

class TestTaskRegistration:
    def test_refresh_all_ratings_is_registered(self):
        """Задача периодического пересчёта зарегистрирована в Celery-приложении.

        Импорт app.tasks обязателен: декоратор @shared_task регистрирует задачу
        в момент импорта модуля. В реальном воркере это делает параметр
        include=["app.tasks"] в celery_app.py.
        """
        import app.tasks  # noqa: F401
        from app.celery_app import celery_app
        assert "app.tasks.refresh_all_ratings" in celery_app.tasks

    def test_update_profile_rating_is_registered(self):
        """Задача событийного пересчёта зарегистрирована в Celery-приложении."""
        import app.tasks  # noqa: F401
        from app.celery_app import celery_app
        assert "app.tasks.update_profile_rating" in celery_app.tasks

    def test_beat_schedule_contains_refresh_all(self):
        """Расписание Beat содержит задачу refresh_all_ratings."""
        from app.celery_app import celery_app
        tasks_in_schedule = {
            entry["task"] for entry in celery_app.conf.beat_schedule.values()
        }
        assert "app.tasks.refresh_all_ratings" in tasks_in_schedule


# ─── Async-хелпер: update_profile_rating ─────────────────────────────────────

class TestAsyncUpdateProfileRating:
    async def test_updates_existing_profile_rating(self, db_session):
        """_async_update_profile_rating создаёт/обновляет строку в profile_ratings."""
        from app.tasks import _async_update_profile_rating

        repo = UserRepository(db_session)
        user, _ = await repo.get_or_create_user(telegram_id=800001)
        profile = await repo.save_profile(
            user.id, display_name="Тест", city="Краснодар"
        )

        with patch(
            "app.tasks._make_session_factory",
            return_value=(_make_mock_engine(), _FakeSessionFactory(db_session)),
        ):
            await _async_update_profile_rating(profile.id)

        result = await db_session.execute(
            select(ProfileRating).where(ProfileRating.profile_id == profile.id)
        )
        rating = result.scalar_one_or_none()
        assert rating is not None
        assert 0 <= rating.combined_score <= 100

    async def test_missing_profile_does_not_raise(self, db_session):
        """Если профиль не найден — задача завершается без исключения."""
        from app.tasks import _async_update_profile_rating

        with patch(
            "app.tasks._make_session_factory",
            return_value=(_make_mock_engine(), _FakeSessionFactory(db_session)),
        ):
            # profile_id=999999 не существует
            await _async_update_profile_rating(999999)

    async def test_engine_dispose_is_called(self, db_session):
        """После выполнения задачи движок всегда закрывается (финальный блок)."""
        from app.tasks import _async_update_profile_rating

        engine_mock = _make_mock_engine()

        with patch(
            "app.tasks._make_session_factory",
            return_value=(engine_mock, _FakeSessionFactory(db_session)),
        ):
            await _async_update_profile_rating(999998)

        engine_mock.dispose.assert_called_once()


# ─── Async-хелпер: refresh_all_ratings ───────────────────────────────────────

class TestAsyncRefreshAllRatings:
    async def test_empty_db_returns_zero(self, db_session):
        """Если профилей нет — возвращает 0 и не падает."""
        from app.tasks import _async_refresh_all_ratings

        with patch(
            "app.tasks._make_session_factory",
            return_value=(_make_mock_engine(), _FakeSessionFactory(db_session)),
        ):
            count = await _async_refresh_all_ratings()

        assert count == 0

    async def test_updates_all_profiles(self, db_session):
        """Задача обновляет рейтинги для всех профилей в БД."""
        from app.tasks import _async_refresh_all_ratings

        repo = UserRepository(db_session)
        created_profile_ids = []
        for tg_id in [900001, 900002, 900003]:
            user, _ = await repo.get_or_create_user(tg_id)
            profile = await repo.save_profile(user.id, display_name=f"U{tg_id}")
            created_profile_ids.append(profile.id)

        with patch(
            "app.tasks._make_session_factory",
            return_value=(_make_mock_engine(), _FakeSessionFactory(db_session)),
        ):
            count = await _async_refresh_all_ratings()

        assert count == 3

        # Все профили должны иметь строку в profile_ratings
        for pid in created_profile_ids:
            result = await db_session.execute(
                select(ProfileRating).where(ProfileRating.profile_id == pid)
            )
            assert result.scalar_one_or_none() is not None

    async def test_engine_dispose_called_after_all_ratings(self, db_session):
        """Движок закрывается после пересчёта всех рейтингов."""
        from app.tasks import _async_refresh_all_ratings

        engine_mock = _make_mock_engine()

        with patch(
            "app.tasks._make_session_factory",
            return_value=(engine_mock, _FakeSessionFactory(db_session)),
        ):
            await _async_refresh_all_ratings()

        engine_mock.dispose.assert_called_once()
