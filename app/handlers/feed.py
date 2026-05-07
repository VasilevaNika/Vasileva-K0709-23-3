"""
Лента анкет: просмотр карточек, лайк / пас, уведомление о мэтче.

Поток:
  1. Пользователь нажимает «Анкета» в меню → показывается первая карточка.
  2. Под карточкой кнопки ❤️ Лайк / 👎 Пас.
  3. После свайпа запись идёт в БД, проверяется взаимность.
  4. При мэтче — уведомление обоим.
  5. Следующая анкета берётся из Redis-кэша; если кэш пуст — пересчитывается.
"""

import logging
from datetime import date
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.repository import UserRepository
from app.services.cache import FeedCache, BATCH_SIZE
from app.services.ranking import build_ranked_feed
from app.services.storage import MinIOStorage
from app.services.swipe_limit import SwipeLimiter, DAILY_SWIPE_LIMIT
from app.tasks import update_profile_rating

logger = logging.getLogger(__name__)


def _age(birth_date: date | None) -> str:
    if birth_date is None:
        return "возраст не указан"
    age = (date.today() - birth_date).days // 365
    # Склонение
    if 11 <= age % 100 <= 19:
        suffix = "лет"
    elif age % 10 == 1:
        suffix = "год"
    elif 2 <= age % 10 <= 4:
        suffix = "года"
    else:
        suffix = "лет"
    return f"{age} {suffix}"


def _gender_label(g: str | None) -> str:
    return {"male": "Мужской", "female": "Женский", "other": "Другой"}.get(g or "", "не указан")


async def _get_next_profile_id(
    user_id: int,
    repo: UserRepository,
    cache: FeedCache,
) -> int | None:
    """
    Извлечь следующий profile_id из Redis.
    Если кэш пуст — перестроить список и положить в Redis.
    """
    remaining = await cache.size(user_id)
    if remaining == 0:
        ranked = await build_ranked_feed(repo.session, viewer_user_id=user_id, limit=BATCH_SIZE)
        if not ranked:
            return None
        await cache.fill(user_id, ranked)

    return await cache.get_next_profile_id(user_id)


async def show_profile_card(
    callback: CallbackQuery,
    profile_id: int,
    repo: UserRepository,
    storage: Optional[MinIOStorage] = None,
    remaining_swipes: Optional[int] = None,
) -> None:
    """Отрисовать карточку профиля с кнопками.

    Фото берётся из MinIO (через публичный URL) если у фото есть storage_key,
    иначе используется Telegram file_id как запасной вариант.
    """
    profile = await repo.get_profile_by_id(profile_id)
    if not profile:
        await callback.message.answer("Анкета не найдена, пропускаем...")
        return

    photos = await repo.get_photos(profile.id)

    gender = _gender_label(profile.gender)
    age_str = _age(profile.birth_date)
    city = profile.city or "город не указан"
    bio = profile.bio or "—"
    interests = profile.interests or "не указаны"

    caption = (
        f"👤 <b>{profile.display_name}</b>, {age_str}\n"
        f"⚧ Пол: {gender}\n"
        f"📍 Город: {city}\n"
        f"📝 О себе: {bio}\n"
        f"🎯 Интересы: {interests}"
    )

    if remaining_swipes is not None:
        caption += f"\n\n🔄 Осталось свайпов сегодня: {remaining_swipes}/{DAILY_SWIPE_LIMIT}"

    kb = InlineKeyboardBuilder()
    kb.button(text="❤️ Лайк", callback_data=f"swipe:like:{profile_id}")
    kb.button(text="👎 Пас", callback_data=f"swipe:pass:{profile_id}")
    kb.adjust(2)

    if photos:
        # Предпочитаем MinIO URL (постоянное хранилище) перед Telegram file_id
        photo_source: str = photos[0].file_id
        if storage is not None and photos[0].storage_key:
            photo_source = storage.get_public_url(photos[0].storage_key)

        await callback.message.answer_photo(
            photo=photo_source,
            caption=caption,
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )
    else:
        await callback.message.answer(
            text=caption,
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )


def register_feed_router(router: Router):
    """Регистрирует хендлеры ленты анкет."""

    @router.callback_query(F.data == "menu:anketa")
    async def open_feed(
        callback: CallbackQuery,
        repo: UserRepository,
        feed_cache: FeedCache,
        swipe_limiter: SwipeLimiter,
        storage: Optional[MinIOStorage] = None,
    ):
        """Открыть ленту — показать первую анкету."""
        user = await repo.get_user_by_telegram_id(callback.from_user.id)
        if not user or not user.is_registered:
            await callback.answer("Сначала нужно зарегистрироваться!", show_alert=True)
            return

        if await swipe_limiter.is_limit_reached(user.id):
            await callback.message.answer(
                f"⏳ <b>Лимит свайпов исчерпан</b>\n\n"
                f"Вы использовали все {DAILY_SWIPE_LIMIT} свайпов на сегодня.\n"
                "Возвращайтесь завтра — лимит сбрасывается в полночь! 🌙",
                parse_mode="HTML",
            )
            await callback.answer()
            return

        profile_id = await _get_next_profile_id(user.id, repo, feed_cache)
        if profile_id is None:
            await callback.message.answer(
                "😔 Пока анкет нет. Загляните позже — новые пользователи появляются каждый день!"
            )
            await callback.answer()
            return

        remaining = await swipe_limiter.remaining(user.id)
        await show_profile_card(callback, profile_id, repo, storage, remaining_swipes=remaining)
        await callback.answer()

    @router.callback_query(F.data.startswith("swipe:"))
    async def handle_swipe(
        callback: CallbackQuery,
        repo: UserRepository,
        feed_cache: FeedCache,
        swipe_limiter: SwipeLimiter,
        bot: Bot,
        storage: Optional[MinIOStorage] = None,
    ):
        """Обработать лайк или пас, затем показать следующую анкету."""
        _, action, profile_id_str = callback.data.split(":", 2)
        profile_id = int(profile_id_str)

        viewer_user = await repo.get_user_by_telegram_id(callback.from_user.id)
        if not viewer_user:
            await callback.answer("Ошибка сессии.", show_alert=True)
            return

        # Проверяем лимит до записи свайпа
        if await swipe_limiter.is_limit_reached(viewer_user.id):
            await callback.answer(
                f"⏳ Лимит {DAILY_SWIPE_LIMIT} свайпов в день исчерпан. Возвращайтесь завтра!",
                show_alert=True,
            )
            return

        target_profile = await repo.get_profile_by_id(profile_id)
        if not target_profile:
            await callback.answer()
            return

        # Проверяем, не было ли уже свайпа (защита от двойного нажатия)
        existing = await repo.get_swipe(viewer_user.id, target_profile.user_id)
        if not existing:
            await repo.record_swipe(viewer_user.id, target_profile.user_id, action)
            await repo.session.commit()

            # Увеличиваем счётчик дневных свайпов
            await swipe_limiter.increment(viewer_user.id)

            try:
                update_profile_rating.delay(target_profile.id)
            except Exception as celery_exc:
                logger.warning("Celery недоступен, задача обновления рейтинга пропущена: %s", celery_exc)

            if action == "like":
                # Проверяем взаимный лайк
                is_mutual = await repo.check_mutual_like(viewer_user.id, target_profile.user_id)
                if is_mutual:
                    existing_match = await repo.get_match(viewer_user.id, target_profile.user_id)
                    if not existing_match:
                        match = await repo.create_match(viewer_user.id, target_profile.user_id)
                        await repo.session.commit()
                        await _notify_match(bot, repo, match, viewer_user.id, target_profile.user_id)

        remaining = await swipe_limiter.remaining(viewer_user.id)

        # Если лимит только что исчерпан — сообщаем и не показываем следующую анкету
        if remaining == 0:
            await callback.message.answer(
                f"⏳ <b>Лимит свайпов исчерпан!</b>\n\n"
                f"Вы использовали все {DAILY_SWIPE_LIMIT} свайпов на сегодня.\n"
                "Возвращайтесь завтра — лимит сбрасывается в полночь! 🌙",
                parse_mode="HTML",
            )
            await callback.answer()
            return

        # Показываем следующую анкету
        next_id = await _get_next_profile_id(viewer_user.id, repo, feed_cache)
        if next_id is None:
            await callback.message.answer(
                "🎉 Вы просмотрели все доступные анкеты!\n"
                "Возвращайтесь позже — список обновляется."
            )
        else:
            await show_profile_card(callback, next_id, repo, storage, remaining_swipes=remaining)

        await callback.answer()


async def _notify_match(
    bot: Bot,
    repo: UserRepository,
    match,
    user_a_id: int,
    user_b_id: int,
) -> None:
    """Отправить уведомление о мэтче обоим пользователям."""
    user_a = await repo.session.get(__import__("app.models", fromlist=["User"]).User, user_a_id)
    user_b = await repo.session.get(__import__("app.models", fromlist=["User"]).User, user_b_id)

    profile_a = await repo.get_profile_by_user_id(user_a_id)
    profile_b = await repo.get_profile_by_user_id(user_b_id)

    name_a = profile_a.display_name if profile_a else "Пользователь"
    name_b = profile_b.display_name if profile_b else "Пользователь"

    kb = InlineKeyboardBuilder()
    kb.button(text="💬 Написать", callback_data=f"chat:open:{match.id}")
    kb.adjust(1)

    if user_a:
        try:
            await bot.send_message(
                user_a.telegram_id,
                f"🎉 <b>Мэтч!</b>\n\n{name_b} тоже поставил(а) вам лайк!\nНачните общение прямо сейчас.",
                reply_markup=kb.as_markup(),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning("Cannot notify user_a %s: %s", user_a.telegram_id, e)

    if user_b:
        try:
            await bot.send_message(
                user_b.telegram_id,
                f"🎉 <b>Мэтч!</b>\n\n{name_a} тоже поставил(а) вам лайк!\nНачните общение прямо сейчас.",
                reply_markup=kb.as_markup(),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning("Cannot notify user_b %s: %s", user_b.telegram_id, e)
