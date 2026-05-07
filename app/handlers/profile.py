"""
Хендлер «Мой профиль»: просмотр и рейтинг своей анкеты, кнопка редактирования.
"""

import logging
from datetime import date
from typing import Optional

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.repository import UserRepository
from app.services.ranking import refresh_profile_rating
from app.services.storage import MinIOStorage

logger = logging.getLogger(__name__)


def _age(birth_date: date | None) -> str:
    if birth_date is None:
        return "не указан"
    age = (date.today() - birth_date).days // 365
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


def register_profile_router(router: Router):
    """Регистрирует хендлеры раздела «Мой профиль»."""

    @router.callback_query(F.data == "menu:my_profile")
    async def open_my_profile(
        callback: CallbackQuery,
        repo: UserRepository,
        storage: Optional[MinIOStorage] = None,
    ):
        """Показать анкету пользователя."""
        user = await repo.get_user_by_telegram_id(callback.from_user.id)
        if not user or not user.is_registered:
            await callback.answer("Сначала нужно зарегистрироваться!", show_alert=True)
            return

        profile = await repo.get_profile_by_user_id(user.id)
        if not profile:
            await callback.message.answer("Профиль не найден. Пройдите регистрацию через /register.")
            await callback.answer()
            return

        photos = await repo.get_photos(profile.id)

        # Обновляем рейтинг
        rating = await refresh_profile_rating(repo.session, profile)
        await repo.session.commit()

        gender = _gender_label(profile.gender)
        age_str = _age(profile.birth_date)
        city = profile.city or "не указан"
        bio = profile.bio or "—"
        interests = profile.interests or "не указаны"

        text = (
            f"📋 <b>Ваш профиль</b>\n\n"
            f"👤 <b>{profile.display_name}</b>, {age_str}\n"
            f"⚧ Пол: {gender}\n"
            f"📍 Город: {city}\n"
            f"📝 О себе: {bio}\n"
            f"🎯 Интересы: {interests}\n"
            f"🖼 Фото: {len(photos)} шт.\n\n"
            f"📊 <b>Заполненность анкеты:</b> {profile.profile_completeness}%\n\n"
            f"⭐ <b>Рейтинг:</b>\n"
            f"  • Первичный: {rating.primary_score:.1f}/100\n"
            f"  • Поведенческий: {rating.behavior_score:.1f}/100\n"
            f"  • Итоговый: {rating.combined_score:.1f}/100"
        )

        kb = InlineKeyboardBuilder()
        kb.button(text="✏️ Редактировать профиль", callback_data="profile:edit")
        kb.button(text="🔙 В меню", callback_data="back:menu")
        kb.adjust(1)

        if photos:
            # Используем MinIO URL если фото загружено в хранилище,
            # иначе — Telegram file_id как резервный вариант
            photo_source: str = photos[0].file_id
            if storage is not None and photos[0].storage_key:
                photo_source = storage.get_public_url(photos[0].storage_key)

            await callback.message.answer_photo(
                photo=photo_source,
                caption=text,
                reply_markup=kb.as_markup(),
                parse_mode="HTML",
            )
        else:
            await callback.message.answer(
                text=text,
                reply_markup=kb.as_markup(),
                parse_mode="HTML",
            )

        await callback.answer()

    @router.callback_query(F.data == "profile:edit")
    async def edit_profile(callback: CallbackQuery, state: FSMContext, repo: UserRepository):
        """Запустить редактирование профиля через FSM регистрации."""
        from app.handlers.registration import RegistrationStates
        user = await repo.get_user_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer("Ошибка сессии.", show_alert=True)
            return

        await state.update_data(user_id=user.id)
        await callback.message.answer(
            "✏️ <b>Редактирование профиля</b>\n\n"
            "Пройдите шаги заново — введите новые данные.\n\n"
            "Шаг 1/11: Как вас зовут?\n"
            "<i>(Введите ваше имя)</i>",
            parse_mode="HTML",
        )
        await state.set_state(RegistrationStates.waiting_for_name)
        await callback.answer()
