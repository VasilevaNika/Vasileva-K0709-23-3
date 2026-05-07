"""
Тесты алгоритма ранжирования (app/services/ranking.py).

Проверяем три уровня рейтинга:
  - Первичный (статика профиля)
  - Поведенческий (реакции других пользователей)
  - Комбинированный (взвешенная смесь)
А также функции refresh_profile_rating и build_ranked_feed.
"""

from datetime import date

from sqlalchemy import select

from app.models import ProfileRating
from app.repository import UserRepository
from app.services.ranking import (
    W_PRIMARY,
    W_BEHAVIOR,
    build_ranked_feed,
    compute_behavior_score,
    compute_combined_score,
    compute_primary_score,
    refresh_profile_rating,
)


# ─── Вспомогательная функция ─────────────────────────────────────────────────

async def _make_registered_user(session, telegram_id: int, **profile_kwargs):
    """Создаёт пользователя с заполненным профилем; user.is_registered=True."""
    repo = UserRepository(session)
    user, _ = await repo.get_or_create_user(telegram_id)
    display_name = profile_kwargs.pop("display_name", f"User{telegram_id}")
    profile = await repo.save_profile(user.id, display_name=display_name, **profile_kwargs)
    return user, profile


# ─── Первичный рейтинг ───────────────────────────────────────────────────────

class TestPrimaryScore:
    async def test_empty_profile_has_low_score(self, db_session):
        _, profile = await _make_registered_user(db_session, telegram_id=1001)
        score = await compute_primary_score(db_session, profile, viewer_prefs=None)
        # Только display_name заполнено → completeness=15
        assert 0 < score < 50

    async def test_full_profile_gets_maximum_no_prefs(self, db_session):
        repo = UserRepository(db_session)
        _, profile = await _make_registered_user(
            db_session, telegram_id=1002,
            display_name="Полный Профиль",
            bio="Это описание длиннее десяти символов точно",
            birth_date=date(1995, 3, 20),
            gender="female",
            city="Москва",
            interests="Спорт, Музыка",
        )
        await repo.add_photo(profile.id, file_id="photo_x")
        await repo.add_photo(profile.id, file_id="photo_y")

        score = await compute_primary_score(db_session, profile, viewer_prefs=None)
        # completeness=100 → 40pts; 2 фото → min(2/5, 1)*10 = 4pts; итого 44.0
        assert score >= 44

    async def test_score_is_within_range(self, db_session):
        _, profile = await _make_registered_user(db_session, telegram_id=1003)
        score = await compute_primary_score(db_session, profile, viewer_prefs=None)
        assert 0.0 <= score <= 100.0

    async def test_gender_match_increases_score(self, db_session):
        from app.models import UserPreferences

        _, profile_female = await _make_registered_user(
            db_session, telegram_id=1004, gender="female"
        )

        # Создаём предпочтения, которые совпадают с полом профиля
        viewer_user, _ = await _make_registered_user(db_session, telegram_id=1005)
        prefs_result = await db_session.execute(
            select(UserPreferences).where(UserPreferences.user_id == viewer_user.id)
        )
        prefs = prefs_result.scalar_one_or_none()
        if prefs:
            prefs.preferred_gender = "female"
        await db_session.commit()

        score_with_prefs = await compute_primary_score(db_session, profile_female, prefs)
        score_no_prefs = await compute_primary_score(db_session, profile_female, None)

        assert score_with_prefs >= score_no_prefs


# ─── Поведенческий рейтинг ───────────────────────────────────────────────────

class TestBehaviorScore:
    async def test_new_profile_gets_neutral_score_30(self, db_session):
        _, profile = await _make_registered_user(db_session, telegram_id=2001)
        score = await compute_behavior_score(db_session, profile)
        assert score == 30.0

    async def test_liked_profile_gets_more_than_30(self, db_session):
        _, target = await _make_registered_user(db_session, telegram_id=2002)
        repo = UserRepository(db_session)

        for tg_id in [3001, 3002, 3003]:
            u, _ = await _make_registered_user(db_session, tg_id)
            await repo.record_swipe(u.id, target.id, "like")
        await db_session.commit()

        score = await compute_behavior_score(db_session, target)
        assert score > 30.0

    async def test_all_passes_gives_low_behavior(self, db_session):
        _, target = await _make_registered_user(db_session, telegram_id=2003)
        repo = UserRepository(db_session)

        for tg_id in [4001, 4002, 4003]:
            u, _ = await _make_registered_user(db_session, tg_id)
            await repo.record_swipe(u.id, target.id, "pass")
        await db_session.commit()

        score = await compute_behavior_score(db_session, target)
        # Нет лайков → like_rate=0, match_rate=0, chat_rate=0, boost≈0
        assert score < 30.0

    async def test_score_is_within_range(self, db_session):
        _, profile = await _make_registered_user(db_session, telegram_id=2004)
        score = await compute_behavior_score(db_session, profile)
        assert 0.0 <= score <= 100.0


# ─── Комбинированный рейтинг ─────────────────────────────────────────────────

class TestCombinedScore:
    async def test_combined_equals_weighted_sum(self, db_session):
        _, profile = await _make_registered_user(db_session, telegram_id=5001)
        primary, behavior, combined = await compute_combined_score(
            db_session, profile, viewer_prefs=None
        )
        expected = W_PRIMARY * primary + W_BEHAVIOR * behavior
        assert abs(combined - expected) < 1e-6

    async def test_all_scores_in_range(self, db_session):
        _, profile = await _make_registered_user(db_session, telegram_id=5002)
        p, b, c = await compute_combined_score(db_session, profile, viewer_prefs=None)
        assert 0.0 <= p <= 100.0
        assert 0.0 <= b <= 100.0
        assert 0.0 <= c <= 100.0


# ─── Сохранение рейтинга в БД ────────────────────────────────────────────────

class TestRefreshProfileRating:
    async def test_creates_profile_rating_row(self, db_session):
        _, profile = await _make_registered_user(db_session, telegram_id=6001)

        rating = await refresh_profile_rating(db_session, profile)
        await db_session.commit()

        result = await db_session.execute(
            select(ProfileRating).where(ProfileRating.profile_id == profile.id)
        )
        saved = result.scalar_one_or_none()
        assert saved is not None
        assert saved.combined_score == rating.combined_score

    async def test_updates_existing_rating(self, db_session):
        _, profile = await _make_registered_user(db_session, telegram_id=6002)

        rating1 = await refresh_profile_rating(db_session, profile)
        await db_session.commit()

        # Пересчитываем ещё раз
        rating2 = await refresh_profile_rating(db_session, profile)
        await db_session.commit()

        # Та же строка ProfileRating, ID не изменился
        assert rating1.profile_id == rating2.profile_id
        # Значения остаются в допустимом диапазоне
        assert 0 <= rating2.combined_score <= 100

    async def test_scores_are_rounded_to_2_decimals(self, db_session):
        _, profile = await _make_registered_user(db_session, telegram_id=6003)
        rating = await refresh_profile_rating(db_session, profile)
        await db_session.commit()

        # Проверяем точность округления
        assert rating.primary_score == round(rating.primary_score, 2)
        assert rating.behavior_score == round(rating.behavior_score, 2)
        assert rating.combined_score == round(rating.combined_score, 2)


# ─── Построение ранжированной ленты ─────────────────────────────────────────

class TestBuildRankedFeed:
    async def test_empty_db_returns_empty_list(self, db_session):
        result = await build_ranked_feed(db_session, viewer_user_id=99999, limit=10)
        assert result == []

    async def test_excludes_viewer_own_profile(self, db_session):
        viewer, viewer_profile = await _make_registered_user(db_session, telegram_id=7001)

        result = await build_ranked_feed(db_session, viewer_user_id=viewer.id, limit=10)
        assert viewer_profile.id not in result

    async def test_returns_other_profiles(self, db_session):
        viewer, _ = await _make_registered_user(db_session, telegram_id=7002)

        other_profiles = []
        for tg_id in [7003, 7004, 7005]:
            _, p = await _make_registered_user(db_session, tg_id)
            other_profiles.append(p.id)

        result = await build_ranked_feed(db_session, viewer_user_id=viewer.id, limit=10)
        assert len(result) == 3
        for pid in other_profiles:
            assert pid in result

    async def test_excludes_already_swiped_profiles(self, db_session):
        viewer, _ = await _make_registered_user(db_session, telegram_id=7006)
        target_user, target_profile = await _make_registered_user(db_session, telegram_id=7007)
        repo = UserRepository(db_session)

        await repo.record_swipe(viewer.id, target_user.id, "like")
        await db_session.commit()

        result = await build_ranked_feed(db_session, viewer_user_id=viewer.id, limit=10)
        assert target_profile.id not in result

    async def test_respects_limit_parameter(self, db_session):
        viewer, _ = await _make_registered_user(db_session, telegram_id=7008)

        for tg_id in range(7009, 7020):  # 11 профилей
            await _make_registered_user(db_session, tg_id)

        result = await build_ranked_feed(db_session, viewer_user_id=viewer.id, limit=5)
        assert len(result) <= 5
