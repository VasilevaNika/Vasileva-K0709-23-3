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

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.repository import UserRepository
from app.services.cache import FeedCache, BATCH_SIZE
from app.services.ranking import build_ranked_feed

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
) -> None:
    """Отрисовать карточку профиля с кнопками."""
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

    kb = InlineKeyboardBuilder()
    kb.button(text="❤️ Лайк", callback_data=f"swipe:like:{profile_id}")
    kb.button(text="👎 Пас", callback_data=f"swipe:pass:{profile_id}")
    kb.adjust(2)

    if photos:
        await callback.message.answer_photo(
            photo=photos[0].file_id,
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
    async def open_feed(callback: CallbackQuery, repo: UserRepository, feed_cache: FeedCache):
        """Открыть ленту — показать первую анкету."""
        user = await repo.get_user_by_telegram_id(callback.from_user.id)
        if not user or not user.is_registered:
            await callback.answer("Сначала нужно зарегистрироваться!", show_alert=True)
            return

        profile_id = await _get_next_profile_id(user.id, repo, feed_cache)
        if profile_id is None:
            await callback.message.answer(
                "😔 Пока анкет нет. Загляните позже — новые пользователи появляются каждый день!"
            )
            await callback.answer()
            return

        await show_profile_card(callback, profile_id, repo)
        await callback.answer()

    @router.callback_query(F.data.startswith("swipe:"))
    async def handle_swipe(
        callback: CallbackQuery,
        repo: UserRepository,
        feed_cache: FeedCache,
        bot: Bot,
    ):
        """Обработать лайк или пас, затем показать следующую анкету."""
        _, action, profile_id_str = callback.data.split(":", 2)
        profile_id = int(profile_id_str)

        viewer_user = await repo.get_user_by_telegram_id(callback.from_user.id)
        if not viewer_user:
            await callback.answer("Ошибка сессии.", show_alert=True)
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

            if action == "like":
                # Проверяем взаимный лайк
                is_mutual = await repo.check_mutual_like(viewer_user.id, target_profile.user_id)
                if is_mutual:
                    existing_match = await repo.get_match(viewer_user.id, target_profile.user_id)
                    if not existing_match:
                        match = await repo.create_match(viewer_user.id, target_profile.user_id)
                        await repo.session.commit()
                        await _notify_match(bot, repo, match, viewer_user.id, target_profile.user_id)

        # Показываем следующую анкету
        next_id = await _get_next_profile_id(viewer_user.id, repo, feed_cache)
        if next_id is None:
            await callback.message.answer(
                "🎉 Вы просмотрели все доступные анкеты!\n"
                "Возвращайтесь позже — список обновляется."
            )
        else:
            await show_profile_card(callback, next_id, repo)

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
