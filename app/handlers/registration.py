"""
FSM-машина для пошаговой регистрации нового пользователя.

Шаги:
  1. Имя (display_name)
  2. Описание о себе (bio)
  3. Дата рождения (birth_date) — формат ДД.ММ.ГГГГ
  4. Пол (gender) — inline-кнопки
  5. Город (city)
  6. Интересы (interests) — через inline-кнопки
  7. Фото (photo) — опционально
  8. Предпочтения: пол (preferred_gender)
  9. Предпочтения: возраст min
  10. Предпочтения: возраст max
  11. Предпочтения: город
"""

from datetime import datetime

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.repository import UserRepository


class RegistrationStates(StatesGroup):
    """Состояния FSM для регистрации."""
    waiting_for_name = State()
    waiting_for_bio = State()
    waiting_for_birth_date = State()
    waiting_for_gender = State()
    waiting_for_city = State()
    waiting_for_interests = State()
    waiting_for_photo = State()
    waiting_for_pref_gender = State()
    waiting_for_pref_age_min = State()
    waiting_for_pref_age_max = State()
    waiting_for_pref_city = State()


# ---------- Inline-кнопки ----------

def gender_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="Мужской", callback_data="gender:male")
    kb.button(text="Женский", callback_data="gender:female")
    kb.button(text="Другой", callback_data="gender:other")
    kb.adjust(2)
    return kb


def interests_keyboard() -> InlineKeyboardBuilder:
    interests = [
        "Спорт", "Музыка", "Кино", "Путешествия",
        "Книги", "Игры", "Кулинария", "Искусство",
        "Технологии", "Фотография", "Танцы", "Природа",
    ]
    kb = InlineKeyboardBuilder()
    for interest in interests:
        kb.button(text=f"☐ {interest}", callback_data=f"interest:{interest}")
    kb.button(text="✅ Завершить", callback_data="interests_done")
    kb.adjust(3)
    return kb


def pref_gender_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="Мужчин", callback_data="pref_gender:male")
    kb.button(text="Женщин", callback_data="pref_gender:female")
    kb.button(text="Всех", callback_data="pref_gender:any")
    kb.adjust(2)
    return kb


def yes_no_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="📷 Да, загрузить фото", callback_data="photo_yes")
    kb.button(text="⏭ Пропустить", callback_data="photo_no")
    kb.adjust(2)
    return kb


# ---------- Хендлеры регистрации ----------

def register_registration_router(router: Router):
    """Регистрирует хендлеры FSM-машины регистрации в роутере."""

    @router.message(Command("register"))
    async def cmd_register(message: Message, state: FSMContext, repo: UserRepository):
        """Запуск регистрации или редактирования профиля."""
        user, _ = await repo.get_or_create_user(message.from_user.id)

        # Сохраняем user_id в FSM — он нужен на финальном шаге
        await state.update_data(user_id=user.id)

        if user.is_registered:
            intro = (
                "✏️ Редактирование профиля.\n\n"
                "Пройдите шаги заново — введите новые данные.\n\n"
            )
        else:
            intro = (
                "🎉 Добро пожаловать в Dating Bot!\n\n"
                "Давайте создадим ваш профиль. Это займёт пару минут.\n\n"
            )

        await message.answer(
            intro +
            "Шаг 1/11: Как вас зовут?\n"
            "_(Введите ваше имя)_",
            parse_mode="Markdown",
        )
        await state.set_state(RegistrationStates.waiting_for_name)

    # --- Шаг 1: Имя ---
    @router.message(StateFilter(RegistrationStates.waiting_for_name))
    async def process_name(message: Message, state: FSMContext):
        if len(message.text.strip()) < 2:
            await message.answer("Имя должно быть не менее 2 символов. Попробуйте ещё раз:")
            return
        await state.update_data(display_name=message.text.strip())
        await message.answer(
            "Шаг 2/11: Расскажите немного о себе.\n"
            "_(Можно написать что угодно или пропустить — /skip)_",
            parse_mode="Markdown",
        )
        await state.set_state(RegistrationStates.waiting_for_bio)

    # --- Шаг 2: Bio ---
    @router.message(StateFilter(RegistrationStates.waiting_for_bio))
    async def process_bio(message: Message, state: FSMContext):
        bio = message.text.strip() if message.text.lower() != "/skip" else None
        await state.update_data(bio=bio if bio else None)
        await message.answer(
            "Шаг 3/11: Когда у вас день рождения?\n"
            "_(Формат: ДД.ММ.ГГГГ, например 15.04.2000)_",
        )
        await state.set_state(RegistrationStates.waiting_for_birth_date)

    @router.message(Command("skip"), StateFilter(RegistrationStates.waiting_for_bio))
    async def skip_bio(message: Message, state: FSMContext):
        await state.update_data(bio=None)
        await message.answer(
            "Шаг 3/11: Когда у вас день рождения?\n"
            "_(Формат: ДД.ММ.ГГГГ, например 15.04.2000)_",
        )
        await state.set_state(RegistrationStates.waiting_for_birth_date)

    # --- Шаг 3: Дата рождения ---
    @router.message(StateFilter(RegistrationStates.waiting_for_birth_date))
    async def process_birth_date(message: Message, state: FSMContext):
        try:
            birth_date = datetime.strptime(message.text.strip(), "%d.%m.%Y").date()
            # Простая валидация возраста
            age = (datetime.now().date() - birth_date).days // 365
            if age < 14:
                await message.answer("Вам должно быть минимум 14 лет. Укажите корректную дату:")
                return
            if age > 120:
                await message.answer("Похоже на ошибку. Укажите корректную дату (ДД.ММ.ГГГГ):")
                return
        except ValueError:
            await message.answer(
                "Неверный формат. Используйте ДД.ММ.ГГГГ, например 15.04.2000:"
            )
            return

        await state.update_data(birth_date=birth_date.isoformat())
        await message.answer(
            "Шаг 4/11: Укажите ваш пол:",
            reply_markup=gender_keyboard().as_markup(),
        )
        await state.set_state(RegistrationStates.waiting_for_gender)

    # --- Шаг 4: Пол ---
    @router.callback_query(
        StateFilter(RegistrationStates.waiting_for_gender),
        F.data.startswith("gender:"),
    )
    async def process_gender(callback: CallbackQuery, state: FSMContext):
        gender = callback.data.split(":", 1)[1]
        await state.update_data(gender=gender)
        await callback.message.edit_text(
            "Шаг 5/11: Из какого вы города?",
        )
        await state.set_state(RegistrationStates.waiting_for_city)

    # --- Шаг 5: Город ---
    @router.message(StateFilter(RegistrationStates.waiting_for_city))
    async def process_city(message: Message, state: FSMContext):
        await state.update_data(city=message.text.strip())
        await message.answer(
            "Шаг 6/11: Выберите интересы (можно несколько):",
            reply_markup=interests_keyboard().as_markup(),
        )
        await state.set_state(RegistrationStates.waiting_for_interests)
        await state.update_data(selected_interests=[])

    # --- Шаг 6: Интересы ---
    @router.callback_query(StateFilter(RegistrationStates.waiting_for_interests))
    async def process_interests(callback: CallbackQuery, state: FSMContext):
        if callback.data == "interests_done":
            data = await state.get_data()
            interests = ", ".join(data.get("selected_interests", [])) or None
            await state.update_data(interests=interests)

            await callback.message.edit_text(
                "Шаг 7/11: Хотите загрузить фотографию?",
                reply_markup=yes_no_keyboard().as_markup(),
            )
            await state.set_state(RegistrationStates.waiting_for_photo)
            return

        if callback.data.startswith("interest:"):
            interest = callback.data.split(":", 1)[1]
            data = await state.get_data()
            selected = data.get("selected_interests", [])

            if interest in selected:
                selected.remove(interest)
            else:
                selected.append(interest)

            await state.update_data(selected_interests=selected)

            # Обновляем кнопки — отмечаем выбранные
            kb = InlineKeyboardBuilder()
            all_interests = [
                "Спорт", "Музыка", "Кино", "Путешествия",
                "Книги", "Игры", "Кулинария", "Искусство",
                "Технологии", "Фотография", "Танцы", "Природа",
            ]
            for int_name in all_interests:
                prefix = "☑" if int_name in selected else "☐"
                kb.button(text=f"{prefix} {int_name}", callback_data=f"interest:{int_name}")
            kb.button(text="✅ Завершить", callback_data="interests_done")
            kb.adjust(3)

            await callback.message.edit_reply_markup(reply_markup=kb.as_markup())
            await callback.answer()
            return

    # --- Шаг 7: Фото ---
    @router.callback_query(
        StateFilter(RegistrationStates.waiting_for_photo),
        F.data.in_(["photo_yes", "photo_no"]),
    )
    async def process_photo_decision(callback: CallbackQuery, state: FSMContext):
        if callback.data == "photo_no":
            await state.update_data(photo_file_id=None)
            await _proceed_to_preferences(callback.message, state)
        else:
            await callback.message.edit_text(
                "Отправьте фото (одно изображение). \n"
                "Если хотите пропустить — напишите /skip."
            )
            await state.set_state(RegistrationStates.waiting_for_photo)

    @router.message(
        StateFilter(RegistrationStates.waiting_for_photo),
        F.photo,
    )
    async def process_photo_upload(message: Message, state: FSMContext):
        file_id = message.photo[-1].file_id
        await state.update_data(photo_file_id=file_id)
        await _proceed_to_preferences(message, state)

    @router.message(Command("skip"), StateFilter(RegistrationStates.waiting_for_photo))
    async def skip_photo(message: Message, state: FSMContext):
        await state.update_data(photo_file_id=None)
        await _proceed_to_preferences(message, state)

    # --- Шаг 8: Предпочтения — пол ---
    @router.callback_query(
        StateFilter(RegistrationStates.waiting_for_pref_gender),
        F.data.startswith("pref_gender:"),
    )
    async def process_pref_gender(callback: CallbackQuery, state: FSMContext):
        pref_gender = callback.data.split(":", 1)[1]
        await state.update_data(pref_gender=pref_gender)
        await callback.message.edit_text(
            "Шаг 9/11: Минимальный возраст партнёра:",
        )
        await state.set_state(RegistrationStates.waiting_for_pref_age_min)

    # --- Шаг 9: Предпочтения — возраст min ---
    @router.message(StateFilter(RegistrationStates.waiting_for_pref_age_min))
    async def process_pref_age_min(message: Message, state: FSMContext):
        try:
            age_min = int(message.text.strip())
            if age_min < 14 or age_min > 100:
                raise ValueError
        except ValueError:
            await message.answer("Введите число от 14 до 100:")
            return
        await state.update_data(pref_age_min=age_min)
        await message.answer("Шаг 10/11: Максимальный возраст партнёра:")
        await state.set_state(RegistrationStates.waiting_for_pref_age_max)

    # --- Шаг 10: Предпочтения — возраст max ---
    @router.message(StateFilter(RegistrationStates.waiting_for_pref_age_max))
    async def process_pref_age_max(message: Message, state: FSMContext):
        try:
            age_max = int(message.text.strip())
            if age_max < 14 or age_max > 100:
                raise ValueError
        except ValueError:
            await message.answer("Введите число от 14 до 100:")
            return
        data = await state.get_data()
        age_min = data.get("pref_age_min", 14)
        if age_max < age_min:
            await message.answer(
                f"Максимальный возраст должен быть ≥ минимального ({age_min}). Введите ещё раз:"
            )
            return
        await state.update_data(pref_age_max=age_max)
        await message.answer("Шаг 11/11: Предпочтительный город (или 'Любой'):")
        await state.set_state(RegistrationStates.waiting_for_pref_city)

    # --- Шаг 11: Предпочтения — город ---
    @router.message(StateFilter(RegistrationStates.waiting_for_pref_city))
    async def process_pref_city(message: Message, state: FSMContext, repo: UserRepository):
        pref_city = message.text.strip() if message.text.strip().lower() != "любой" else None
        await state.update_data(pref_city=pref_city)

        # Сохраняем всё в БД
        data = await state.get_data()
        from datetime import date

        birth_date = None
        if data.get("birth_date"):
            birth_date = date.fromisoformat(data["birth_date"])

        profile = await repo.create_profile(
            user_id=data["user_id"],
            display_name=data["display_name"],
            bio=data.get("bio"),
            birth_date=birth_date,
            gender=data.get("gender"),
            city=data.get("city"),
            interests=data.get("interests"),
        )

        # Обновляем предпочтения
        from app.models import UserPreferences
        from sqlalchemy import update

        await repo.session.execute(
            update(UserPreferences)
            .where(UserPreferences.user_id == data["user_id"])
            .values(
                preferred_gender=data.get("pref_gender"),
                age_min=data.get("pref_age_min"),
                age_max=data.get("pref_age_max"),
                preferred_city=data.get("pref_city"),
            )
        )
        await repo.session.commit()

        # Добавляем фото, если есть
        photo_file_id = data.get("photo_file_id")
        if photo_file_id:
            await repo.add_photo(profile.id, photo_file_id)

        await message.answer(
            "🎉 Регистрация завершена!\n\n"
            "Ваш профиль создан.\n"
            f"Полнота заполнения: {profile.profile_completeness}%\n\n"
            "Используйте /menu для главного меню.",
        )
        await state.clear()

    # ---------- Вспомогательные ----------

    async def _proceed_to_preferences(message, state: FSMContext):
        await message.answer(
            "Шаг 8/11: Кого вы ищете? (пол)",
            reply_markup=pref_gender_keyboard().as_markup(),
        )
        await state.set_state(RegistrationStates.waiting_for_pref_gender)
