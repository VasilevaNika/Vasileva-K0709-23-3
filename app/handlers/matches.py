"""
Раздел «Мэтчи»: список мэтчей и чат внутри мэтча.

FSM для чата:
  - Пользователь нажимает «💬 Написать» → устанавливается state ChatStates.in_chat
    с данными о match_id и partner_telegram_id.
  - Все текстовые сообщения в этом состоянии → пересылаются партнёру.
  - /stopchat — выход из чата.
"""

import logging
from datetime import date

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.filters import Command, StateFilter
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.repository import UserRepository
from app.models import User

logger = logging.getLogger(__name__)


class ChatStates(StatesGroup):
    in_chat = State()


def _age(birth_date: date | None) -> str:
    if birth_date is None:
        return "?"
    return str((date.today() - birth_date).days // 365)


def register_matches_router(router: Router):
    """Регистрирует хендлеры мэтчей и чата."""

    @router.callback_query(F.data == "menu:matches")
    async def open_matches(callback: CallbackQuery, repo: UserRepository):
        """Показать список мэтчей."""
        user = await repo.get_user_by_telegram_id(callback.from_user.id)
        if not user or not user.is_registered:
            await callback.answer("Сначала нужно зарегистрироваться!", show_alert=True)
            return

        matches = await repo.get_user_matches(user.id)
        if not matches:
            await callback.message.answer("💔 У вас пока нет мэтчей. Продолжайте листать анкеты!")
            await callback.answer()
            return

        kb = InlineKeyboardBuilder()
        for match in matches:
            partner_id = await repo.get_partner_user_id(match, user.id)
            profile = await repo.get_profile_by_user_id(partner_id)
            label = profile.display_name if profile else f"Пользователь #{partner_id}"
            if profile and profile.birth_date:
                label += f", {_age(profile.birth_date)} лет"
            kb.button(text=f"💬 {label}", callback_data=f"chat:open:{match.id}")
        kb.adjust(1)

        await callback.message.answer(
            f"💌 <b>Ваши мэтчи ({len(matches)}):</b>\n\nВыберите, с кем хотите пообщаться:",
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("chat:open:"))
    async def open_chat(callback: CallbackQuery, state: FSMContext, repo: UserRepository):
        """Открыть чат с конкретным мэтчем."""
        match_id = int(callback.data.split(":", 2)[2])
        user = await repo.get_user_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer("Ошибка сессии.", show_alert=True)
            return

        # Находим мэтч и партнёра
        from sqlalchemy import select
        from app.models import Match
        result = await repo.session.execute(
            select(Match).where(Match.id == match_id)
        )
        match = result.scalar_one_or_none()
        if not match:
            await callback.answer("Мэтч не найден.", show_alert=True)
            return

        partner_user_id = await repo.get_partner_user_id(match, user.id)
        partner = await repo.session.get(User, partner_user_id)
        partner_profile = await repo.get_profile_by_user_id(partner_user_id)
        partner_name = partner_profile.display_name if partner_profile else "Пользователь"

        # Показываем историю сообщений
        messages = await repo.get_messages(match_id, limit=10)

        if messages:
            history = []
            for msg in messages:
                who = "Вы" if msg.sender_id == user.id else partner_name
                history.append(f"<b>{who}:</b> {msg.body}")
            history_text = "\n".join(history)
            await callback.message.answer(
                f"💬 <b>Чат с {partner_name}</b>\n\n{history_text}\n\n"
                "Отправьте сообщение или /stopchat для выхода.",
                parse_mode="HTML",
            )
        else:
            await callback.message.answer(
                f"💬 <b>Чат с {partner_name}</b>\n\n"
                "Сообщений пока нет. Напишите первым!\n"
                "Для выхода: /stopchat",
                parse_mode="HTML",
            )

        await state.set_state(ChatStates.in_chat)
        await state.update_data(
            match_id=match_id,
            partner_telegram_id=partner.telegram_id if partner else None,
            partner_name=partner_name,
        )
        await callback.answer()

    @router.message(Command("stopchat"), StateFilter(ChatStates.in_chat))
    async def stop_chat(message: Message, state: FSMContext):
        """Выход из режима чата."""
        await state.clear()
        await message.answer(
            "👋 Чат завершён. Используйте /menu для главного меню."
        )

    @router.message(StateFilter(ChatStates.in_chat), F.text)
    async def relay_message(
        message: Message,
        state: FSMContext,
        repo: UserRepository,
        bot: Bot,
    ):
        """Переслать сообщение партнёру по мэтчу."""
        data = await state.get_data()
        match_id = data.get("match_id")
        partner_telegram_id = data.get("partner_telegram_id")
        partner_name = data.get("partner_name", "партнёр")

        if not match_id or not partner_telegram_id:
            await message.answer("Ошибка чата. Используйте /menu.")
            await state.clear()
            return

        # Сохраняем сообщение в БД
        sender_user = await repo.get_user_by_telegram_id(message.from_user.id)
        if sender_user:
            await repo.send_message(match_id, sender_user.id, message.text)
            await repo.session.commit()

        # Отправляем партнёру
        try:
            sender_profile = await repo.get_profile_by_user_id(sender_user.id) if sender_user else None
            sender_name = sender_profile.display_name if sender_profile else message.from_user.first_name

            await bot.send_message(
                partner_telegram_id,
                f"💬 <b>{sender_name}:</b> {message.text}",
                parse_mode="HTML",
            )
            await message.answer("✅ Доставлено")
        except Exception as e:
            logger.warning("Cannot relay message to %s: %s", partner_telegram_id, e)
            await message.answer("⚠️ Не удалось доставить сообщение.")
