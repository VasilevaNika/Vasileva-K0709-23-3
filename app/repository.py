from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Profile, ProfilePhoto, UserPreferences, ProfileRating


class UserRepository:
    """CRUD-операции для User и связанных сущностей."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_user_by_telegram_id(self, telegram_id: int) -> User | None:
        """Найти пользователя по Telegram ID."""
        result = await self.session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def create_user(self, telegram_id: int) -> User:
        """Создать нового пользователя."""
        user = User(telegram_id=telegram_id, is_active=True, is_registered=False)
        self.session.add(user)
        await self.session.flush()
        return user

    async def get_or_create_user(self, telegram_id: int) -> tuple[User, bool]:
        """
        Получить существующего пользователя или создать нового.
        Возвращает (user, is_new).
        """
        user = await self.get_user_by_telegram_id(telegram_id)
        if user:
            return user, False
        user = await self.create_user(telegram_id)
        await self.session.commit()
        return user, True

    async def create_profile(
        self,
        user_id: int,
        display_name: str,
        bio: str | None = None,
        birth_date=None,
        gender: str | None = None,
        city: str | None = None,
        interests: str | None = None,
    ) -> Profile:
        """Создать профиль пользователя."""
        completeness = self._calculate_completeness(
            display_name, bio, birth_date, gender, city, interests
        )
        profile = Profile(
            user_id=user_id,
            display_name=display_name,
            bio=bio,
            birth_date=birth_date,
            gender=gender,
            city=city,
            interests=interests,
            profile_completeness=completeness,
        )
        self.session.add(profile)
        await self.session.flush()

        # Создаём запись рейтинга
        rating = ProfileRating(profile_id=profile.id, primary_score=float(completeness))
        self.session.add(rating)

        # Создаём пустые предпочтения
        prefs = UserPreferences(user_id=user_id)
        self.session.add(prefs)

        # Обновляем is_registered
        user = await self.session.get(User, user_id)
        user.is_registered = True

        await self.session.commit()
        return profile

    async def add_photo(self, profile_id: int, file_id: str, storage_key: str | None = None) -> ProfilePhoto:
        """Добавить фото в профиль."""
        # Определяем следующий sort_order
        result = await self.session.execute(
            select(func.coalesce(func.max(ProfilePhoto.sort_order), 0)).where(
                ProfilePhoto.profile_id == profile_id
            )
        )
        max_order = result.scalar()

        photo = ProfilePhoto(
            profile_id=profile_id,
            file_id=file_id,
            storage_key=storage_key,
            sort_order=max_order + 1,
        )
        self.session.add(photo)

        # Обновляем полноту профиля
        profile = await self.session.get(Profile, profile_id)
        profile.profile_completeness = self._calculate_completeness(
            profile.display_name,
            profile.bio,
            profile.birth_date,
            profile.gender,
            profile.city,
            profile.interests,
            photo_count=max_order + 1,
        )

        await self.session.commit()
        return photo

    @staticmethod
    def _calculate_completeness(
        display_name: str | None,
        bio: str | None,
        birth_date,
        gender: str | None,
        city: str | None,
        interests: str | None,
        photo_count: int = 0,
    ) -> int:
        """
        Рассчитать полноту заполнения анкеты (0–100).
        Каждое поле имеет свой вес.
        """
        score = 0
        weights = {
            "display_name": 15,
            "bio": 20,
            "birth_date": 15,
            "gender": 15,
            "city": 15,
            "interests": 10,
            "photos": 10,
        }

        if display_name:
            score += weights["display_name"]
        if bio and len(bio) > 10:
            score += weights["bio"]
        if birth_date:
            score += weights["birth_date"]
        if gender:
            score += weights["gender"]
        if city:
            score += weights["city"]
        if interests:
            score += weights["interests"]
        if photo_count > 0:
            score += min(weights["photos"], photo_count * 5)

        return min(score, 100)
