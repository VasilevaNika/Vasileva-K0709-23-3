"""
Хендлеры: /start (авторегистрация по telegram_id) и /menu.
"""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.repository import UserRepository


def main_menu_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔍 Анкета", callback_data="menu:anketa")
    kb.button(text="📝 Мой профиль", callback_data="menu:my_profile")
    kb.button(text="💌 Мэтчи", callback_data="menu:matches")
    kb.button(text="📊 Статистика", callback_data="menu:stats")
    kb.button(text="⚙ Настройки", callback_data="menu:settings")
    kb.adjust(2)
    return kb


def register_main_router(router: Router):
    """Регистрирует основные хендлеры."""

    @router.message(Command("start"))
    async def cmd_start(message: Message, state: FSMContext, repo: UserRepository):
        """
        Точка входа: /start.
        - Автоматически создаёт/находит пользователя по telegram_id.
        - Если не зарегистрирован — запускает FSM-регистрацию.
        - Если уже зарегистрирован — показывает главное меню.
        """
        user, is_new = await repo.get_or_create_user(message.from_user.id)

        if is_new:
            await message.answer(
                f"👋 Привет, {message.from_user.full_name}!\n\n"
                "Я — Dating Bot. Помогу найти пару.\n"
                "Для начала нужно создать профиль.\n\n"
                "Нажмите /register чтобы начать регистрацию."
            )
            return

        if not user.is_registered:
            await message.answer(
                "Вы уже начинали, но не завершили регистрацию.\n\n"
                "Нажмите /register чтобы продолжить."
            )
            return

        # Зарегистрированный пользователь
        await state.clear()
        await message.answer(
            f"👋 С возвращением, {user.profile.display_name if user.profile else 'друг'}!\n\n"
            "Выберите действие:",
            reply_markup=main_menu_keyboard().as_markup(),
        )

    @router.message(Command("menu"))
    async def cmd_menu(message: Message, state: FSMContext, repo: UserRepository):
        """Главное меню для зарегистрированных."""
        # Сбрасываем FSM-состояние (если пользователь застрял где-то)
        current_state = await state.get_state()
        if current_state:
            await state.clear()
            await message.answer("⚠️ Текущая операция отменена. Главное меню:")

        user = await repo.get_user_by_telegram_id(message.from_user.id)
        if not user or not user.is_registered:
            await message.answer(
                "Сначала нужно зарегистрироваться!\n"
                "Нажмите /start или /register."
            )
            return

        await message.answer(
            f"📱 Главное меню\n\n"
            f"Профиль: {user.profile.display_name} "
            f"(заполнено {user.profile.profile_completeness}%)",
            reply_markup=main_menu_keyboard().as_markup(),
        )

    @router.callback_query(F.data == "menu:settings")
    async def menu_settings(callback: CallbackQuery, repo: UserRepository):
        """Настройки — показываем текущие предпочтения."""
        user = await repo.get_user_by_telegram_id(callback.from_user.id)
        if not user or not user.is_registered:
            await callback.answer("Сначала нужно зарегистрироваться!", show_alert=True)
            return

        from sqlalchemy import select
        from app.models import UserPreferences
        result = await repo.session.execute(
            select(UserPreferences).where(UserPreferences.user_id == user.id)
        )
        prefs = result.scalar_one_or_none()

        if prefs:
            gender_map = {"male": "Мужчин", "female": "Женщин", "any": "Всех"}
            pref_gender = gender_map.get(prefs.preferred_gender or "any", "Всех")
            age_range = f"{prefs.age_min or 14}–{prefs.age_max or 99}"
            pref_city = prefs.preferred_city or "Любой"
            text = (
                f"⚙ <b>Настройки поиска</b>\n\n"
                f"Ищу: {pref_gender}\n"
                f"Возраст: {age_range}\n"
                f"Город: {pref_city}\n\n"
                "Для изменения пройдите регистрацию повторно: /register"
            )
        else:
            text = "⚙ Настройки не найдены. Пройдите /register."

        kb = InlineKeyboardBuilder()
        kb.button(text="🔙 В меню", callback_data="back:menu")
        await callback.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
        await callback.answer()

    @router.callback_query(F.data == "back:menu")
    async def back_to_menu(callback: CallbackQuery, state: FSMContext, repo: UserRepository):
        """Вернуться в главное меню."""
        await state.clear()
        user = await repo.get_user_by_telegram_id(callback.from_user.id)
        name = "друг"
        completeness = 0
        if user and user.profile:
            name = user.profile.display_name
            completeness = user.profile.profile_completeness
        await callback.message.answer(
            f"📱 <b>Главное меню</b>\n\nПрофиль: {name} (заполнено {completeness}%)",
            reply_markup=main_menu_keyboard().as_markup(),
            parse_mode="HTML",
        )
        await callback.answer()
