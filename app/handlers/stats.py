"""
Хендлер «Статистика»: лайки, пасы, мэтчи, конверсия, остаток свайпов.
"""

import logging
from datetime import date

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.repository import UserRepository
from app.services.swipe_limit import SwipeLimiter, DAILY_SWIPE_LIMIT

logger = logging.getLogger(__name__)


def register_stats_router(router: Router):
    """Регистрирует хендлер статистики."""

    @router.callback_query(F.data == "menu:stats")
    async def show_stats(
        callback: CallbackQuery,
        repo: UserRepository,
        swipe_limiter: SwipeLimiter,
    ):
        user = await repo.get_user_by_telegram_id(callback.from_user.id)
        if not user or not user.is_registered:
            await callback.answer("Сначала нужно зарегистрироваться!", show_alert=True)
            return

        stats = await repo.get_user_stats(user.id)
        remaining = await swipe_limiter.remaining(user.id)
        used_today = DAILY_SWIPE_LIMIT - remaining

        # Дата регистрации
        days_registered = (date.today() - user.created_at.date()).days

        text = (
            f"📊 <b>Ваша статистика</b>\n\n"
            f"👍 Лайков отправлено: <b>{stats['likes_sent']}</b>\n"
            f"👎 Пасов отправлено: <b>{stats['passes_sent']}</b>\n"
            f"❤️ Лайков получено: <b>{stats['likes_received']}</b>\n"
            f"🎉 Мэтчей: <b>{stats['matches']}</b>\n"
            f"📈 Конверсия лайк → мэтч: <b>{stats['match_rate']}%</b>\n\n"
            f"🔄 Свайпов сегодня: <b>{used_today}/{DAILY_SWIPE_LIMIT}</b>\n"
            f"⏳ Осталось свайпов: <b>{remaining}</b>\n\n"
            f"📅 Дней в сервисе: <b>{days_registered}</b>"
        )

        kb = InlineKeyboardBuilder()
        kb.button(text="🔙 В меню", callback_data="back:menu")
        await callback.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
        await callback.answer()
