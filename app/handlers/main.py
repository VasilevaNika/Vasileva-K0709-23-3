"""
Хендлеры: /start (авторегистрация по telegram_id) и /menu.
"""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.repository import UserRepository
from app.handlers.registration import RegistrationStates


def main_menu_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔍 Анкета", callback_data="menu:anketa")
    kb.button(text("📝 Мой профиль"), callback_data="menu:my_profile")
    kb.button(text="💌 Мэтчи", callback_data="menu:matches")
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

    @router.callback_query(F.data.startswith("menu:"))
    async def menu_callback(callback: CallbackQuery, state: FSMContext, repo: UserRepository):
        """Обработка кнопок главного меню (заглушки для будущих этапов)."""
        action = callback.data.split(":", 1)[1]

        messages = {
            "anketa": "🔍 Раздел «Анкета» — в разработке (Этап 3) 🚧",
            "my_profile": "📝 Раздел «Мой профиль» — в разработке 🚧",
            "matches": "💌 Раздел «Мэтчи» — в разработке (Этап 3) 🚧",
            "settings": "⚙ Раздел «Настройки» — в разработке 🚧",
        }

        await callback.message.answer(
            messages.get(action, "Раздел в разработке")
        )
        await callback.answer()
