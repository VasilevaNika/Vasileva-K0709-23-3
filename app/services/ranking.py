"""
Алгоритм ранжирования анкет — три уровня:

Уровень 1 — Первичный рейтинг (статика профиля):
  - Полнота анкеты
  - Количество фото
  - Совпадение с предпочтениями просматривающего (пол, возраст, город)

Уровень 2 — Поведенческий рейтинг (реакции других):
  - Общее количество лайков
  - Соотношение лайков к общему числу свайпов (rate)
  - Частота мэтчей (лайки, давшие мэтч / все лайки)
  - Активность в чате после мэтча

Уровень 3 — Комбинированный:
  - combined = 0.4 * primary_norm + 0.6 * behavior_norm
  - Итоговое значение 0..100
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Profile,
    ProfilePhoto,
    ProfileRating,
    UserPreferences,
    Swipe,
    Match,
    Message,
    User,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ─── весовые коэффициенты ──────────────────────────────────────────────────

W_PRIMARY = 0.4
W_BEHAVIOR = 0.6

# Первичный рейтинг (сумма весов = 100)
P_COMPLETENESS = 40   # полнота анкеты
P_PHOTOS = 10         # фото
P_GENDER_MATCH = 20   # совпадение пола
P_AGE_MATCH = 20      # возраст в диапазоне
P_CITY_MATCH = 10     # город

# Поведенческий рейтинг (сумма весов = 100)
B_LIKE_RATE = 40      # % лайков от всех свайпов
B_MATCH_RATE = 30     # % мэтчей от лайков
B_CHAT_RATE = 20      # % мэтчей с сообщениями
B_TOTAL_LIKES = 10    # абсолютное число лайков (мягкий буст)


def _age_from_birth(birth_date: date | None) -> int | None:
    if birth_date is None:
        return None
    return (date.today() - birth_date).days // 365


# ─── Первичный рейтинг ────────────────────────────────────────────────────

async def compute_primary_score(
    session: AsyncSession,
    profile: Profile,
    viewer_prefs: UserPreferences | None,
) -> float:
    """
    Рассчитать первичный рейтинг анкеты profile с точки зрения viewer_prefs.
    Возвращает значение 0..100.
    """
    score = 0.0

    # Полнота анкеты
    score += (profile.profile_completeness / 100) * P_COMPLETENESS

    # Количество фото (max 5 дают полный балл)
    result = await session.execute(
        select(func.count()).where(ProfilePhoto.profile_id == profile.id)
    )
    photo_count = result.scalar() or 0
    score += min(photo_count / 5, 1.0) * P_PHOTOS

    if viewer_prefs is None:
        return min(score, 100.0)

    profile_age = _age_from_birth(profile.birth_date)

    # Совпадение пола
    if viewer_prefs.preferred_gender in (None, "any"):
        score += P_GENDER_MATCH
    elif profile.gender and profile.gender == viewer_prefs.preferred_gender:
        score += P_GENDER_MATCH

    # Возраст в диапазоне предпочтений
    if profile_age is not None:
        age_min = viewer_prefs.age_min or 14
        age_max = viewer_prefs.age_max or 99
        if age_min <= profile_age <= age_max:
            score += P_AGE_MATCH
        else:
            # Частичный балл — чем дальше, тем меньше
            gap = min(abs(profile_age - age_min), abs(profile_age - age_max))
            partial = max(0.0, 1.0 - gap / 10)
            score += partial * P_AGE_MATCH

    # Город
    if viewer_prefs.preferred_city is None:
        score += P_CITY_MATCH
    elif (
        profile.city
        and viewer_prefs.preferred_city
        and profile.city.lower() == viewer_prefs.preferred_city.lower()
    ):
        score += P_CITY_MATCH

    return min(score, 100.0)


# ─── Поведенческий рейтинг ────────────────────────────────────────────────

async def compute_behavior_score(
    session: AsyncSession,
    profile: Profile,
) -> float:
    """
    Рассчитать поведенческий рейтинг анкеты.
    Возвращает значение 0..100.
    """
    user_id = profile.user_id

    # Всего свайпов в адрес пользователя
    total_result = await session.execute(
        select(func.count()).where(Swipe.to_user_id == user_id)
    )
    total_swipes = total_result.scalar() or 0

    # Лайков в адрес пользователя
    likes_result = await session.execute(
        select(func.count()).where(
            and_(Swipe.to_user_id == user_id, Swipe.action == "like")
        )
    )
    likes = likes_result.scalar() or 0

    if total_swipes == 0:
        # Новый профиль — нейтральный балл
        return 30.0

    score = 0.0

    # Доля лайков
    like_rate = likes / total_swipes
    score += like_rate * B_LIKE_RATE

    # Доля мэтчей от лайков
    matches_result = await session.execute(
        select(func.count()).where(
            (Match.user_a_id == user_id) | (Match.user_b_id == user_id)
        )
    )
    match_count = matches_result.scalar() or 0
    match_rate = match_count / max(likes, 1)
    score += min(match_rate, 1.0) * B_MATCH_RATE

    # Доля мэтчей с хотя бы одним сообщением
    if match_count > 0:
        active_chats_result = await session.execute(
            select(func.count(Match.id.distinct())).join(
                Message, Message.match_id == Match.id
            ).where(
                (Match.user_a_id == user_id) | (Match.user_b_id == user_id)
            )
        )
        active_chats = active_chats_result.scalar() or 0
        chat_rate = active_chats / match_count
        score += chat_rate * B_CHAT_RATE

    # Мягкий буст за количество лайков (log-шкала)
    import math
    likes_boost = min(math.log10(likes + 1) / 3, 1.0)
    score += likes_boost * B_TOTAL_LIKES

    return min(score, 100.0)


# ─── Комбинированный рейтинг ──────────────────────────────────────────────

async def compute_combined_score(
    session: AsyncSession,
    profile: Profile,
    viewer_prefs: UserPreferences | None,
) -> tuple[float, float, float]:
    """
    Возвращает (primary_score, behavior_score, combined_score) все в 0..100.
    """
    primary = await compute_primary_score(session, profile, viewer_prefs)
    behavior = await compute_behavior_score(session, profile)
    combined = W_PRIMARY * primary + W_BEHAVIOR * behavior
    return primary, behavior, combined


# ─── Обновление кэша рейтингов в БД ──────────────────────────────────────

async def refresh_profile_rating(
    session: AsyncSession,
    profile: Profile,
) -> ProfileRating:
    """
    Пересчитать и сохранить рейтинг профиля (без учёта конкретного viewer).
    Используется для фоновых задач и заполнения profile_ratings.
    """
    primary = await compute_primary_score(session, profile, viewer_prefs=None)
    behavior = await compute_behavior_score(session, profile)
    combined = W_PRIMARY * primary + W_BEHAVIOR * behavior

    result = await session.execute(
        select(ProfileRating).where(ProfileRating.profile_id == profile.id)
    )
    rating = result.scalar_one_or_none()

    if rating is None:
        rating = ProfileRating(profile_id=profile.id)
        session.add(rating)

    rating.primary_score = round(primary, 2)
    rating.behavior_score = round(behavior, 2)
    rating.combined_score = round(combined, 2)
    rating.updated_at = datetime.utcnow()

    await session.flush()
    return rating


# ─── Построение ранжированной ленты ───────────────────────────────────────

async def build_ranked_feed(
    session: AsyncSession,
    viewer_user_id: int,
    limit: int = 50,
) -> list[int]:
    """
    Вернуть список profile_id, ранжированных для viewer_user_id.
    Исключает:
      - собственный профиль
      - уже просмотренные (есть запись в swipes)
      - неактивных пользователей
    """
    # Уже сделанные свайпы viewer
    swiped_result = await session.execute(
        select(Swipe.to_user_id).where(Swipe.from_user_id == viewer_user_id)
    )
    swiped_user_ids = {row[0] for row in swiped_result.all()}
    swiped_user_ids.add(viewer_user_id)

    # Предпочтения viewer
    prefs_result = await session.execute(
        select(UserPreferences).where(UserPreferences.user_id == viewer_user_id)
    )
    viewer_prefs = prefs_result.scalar_one_or_none()

    # Все кандидаты (активные, зарегистрированные, с профилем)
    candidates_result = await session.execute(
        select(Profile).join(User, User.id == Profile.user_id).where(
            and_(
                User.is_active,
                User.is_registered,
                Profile.user_id.notin_(swiped_user_ids),
            )
        )
    )
    profiles = candidates_result.scalars().all()

    if not profiles:
        return []

    # Считаем рейтинг для каждого
    scored: list[tuple[float, int]] = []
    for profile in profiles:
        _, _, combined = await compute_combined_score(session, profile, viewer_prefs)
        scored.append((combined, profile.id))

    # Сортируем по убыванию combined score
    scored.sort(key=lambda x: x[0], reverse=True)

    return [pid for _, pid in scored[:limit]]
