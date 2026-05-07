from datetime import datetime
from typing import Optional

from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Profile, ProfilePhoto, UserPreferences, ProfileRating, Swipe, Match, Message


class UserRepository:
    """CRUD-операции для User и связанных сущностей."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_user_by_telegram_id(self, telegram_id: int) -> User | None:
        """Найти пользователя по Telegram ID (с жадной загрузкой profile и preferences)."""
        result = await self.session.execute(
            select(User)
            .options(selectinload(User.profile), selectinload(User.preferences))
            .where(User.telegram_id == telegram_id)
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

    async def save_profile(
        self,
        user_id: int,
        display_name: str,
        bio: str | None = None,
        birth_date=None,
        gender: str | None = None,
        city: str | None = None,
        interests: str | None = None,
    ) -> Profile:
        """Создать или обновить профиль пользователя (upsert)."""
        completeness = self._calculate_completeness(
            display_name, bio, birth_date, gender, city, interests
        )

        # Ищем существующий профиль
        result = await self.session.execute(
            select(Profile).where(Profile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()

        if profile is None:
            profile = Profile(user_id=user_id)
            self.session.add(profile)

        profile.display_name = display_name
        profile.bio = bio
        profile.birth_date = birth_date
        profile.gender = gender
        profile.city = city
        profile.interests = interests
        profile.profile_completeness = completeness
        profile.updated_at = datetime.utcnow()
        await self.session.flush()

        # Создаём/обновляем запись рейтинга
        rating_result = await self.session.execute(
            select(ProfileRating).where(ProfileRating.profile_id == profile.id)
        )
        rating = rating_result.scalar_one_or_none()
        if rating is None:
            rating = ProfileRating(profile_id=profile.id)
            self.session.add(rating)
        rating.primary_score = float(completeness)

        # Создаём пустые предпочтения, если нет
        prefs_result = await self.session.execute(
            select(UserPreferences).where(UserPreferences.user_id == user_id)
        )
        if prefs_result.scalar_one_or_none() is None:
            self.session.add(UserPreferences(user_id=user_id))

        # Помечаем пользователя как зарегистрированного
        user = await self.session.get(User, user_id)
        user.is_registered = True

        await self.session.commit()
        return profile

    # Оставляем псевдоним для обратной совместимости
    async def create_profile(self, user_id, display_name, bio=None,
                              birth_date=None, gender=None, city=None, interests=None):
        return await self.save_profile(user_id, display_name, bio, birth_date, gender, city, interests)

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

    async def get_profile_by_id(self, profile_id: int) -> Optional[Profile]:
        """Получить профиль по ID."""
        result = await self.session.execute(
            select(Profile).where(Profile.id == profile_id)
        )
        return result.scalar_one_or_none()

    async def get_profile_by_user_id(self, user_id: int) -> Optional[Profile]:
        """Получить профиль по user_id."""
        result = await self.session.execute(
            select(Profile).where(Profile.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_photos(self, profile_id: int) -> list[ProfilePhoto]:
        """Получить фотографии профиля."""
        result = await self.session.execute(
            select(ProfilePhoto)
            .where(ProfilePhoto.profile_id == profile_id)
            .order_by(ProfilePhoto.sort_order)
        )
        return list(result.scalars().all())

    # ─── Свайпы ───────────────────────────────────────────────────────────

    async def record_swipe(
        self, from_user_id: int, to_user_id: int, action: str
    ) -> Swipe:
        """Записать действие свайпа ('like' | 'pass')."""
        swipe = Swipe(
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            action=action,
            created_at=datetime.utcnow(),
        )
        self.session.add(swipe)
        await self.session.flush()
        return swipe

    async def get_swipe(
        self, from_user_id: int, to_user_id: int
    ) -> Optional[Swipe]:
        """Найти свайп между двумя пользователями."""
        result = await self.session.execute(
            select(Swipe).where(
                and_(
                    Swipe.from_user_id == from_user_id,
                    Swipe.to_user_id == to_user_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def check_mutual_like(
        self, user_a_id: int, user_b_id: int
    ) -> bool:
        """Проверить, поставили ли оба пользователя лайк друг другу."""
        result = await self.session.execute(
            select(func.count()).where(
                and_(
                    Swipe.from_user_id.in_([user_a_id, user_b_id]),
                    Swipe.to_user_id.in_([user_a_id, user_b_id]),
                    Swipe.from_user_id != Swipe.to_user_id,
                    Swipe.action == "like",
                )
            )
        )
        return (result.scalar() or 0) >= 2

    # ─── Мэтчи ────────────────────────────────────────────────────────────

    async def get_match(self, user_a_id: int, user_b_id: int) -> Optional[Match]:
        """Найти мэтч между двумя пользователями."""
        a, b = sorted([user_a_id, user_b_id])
        result = await self.session.execute(
            select(Match).where(
                and_(Match.user_a_id == a, Match.user_b_id == b)
            )
        )
        return result.scalar_one_or_none()

    async def create_match(self, user_a_id: int, user_b_id: int) -> Match:
        """Создать мэтч (canonical order: a < b)."""
        a, b = sorted([user_a_id, user_b_id])
        match = Match(user_a_id=a, user_b_id=b, created_at=datetime.utcnow())
        self.session.add(match)
        await self.session.flush()
        return match

    async def get_user_matches(self, user_id: int) -> list[Match]:
        """Получить все мэтчи пользователя."""
        result = await self.session.execute(
            select(Match).where(
                or_(Match.user_a_id == user_id, Match.user_b_id == user_id)
            ).order_by(Match.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_partner_user_id(self, match: Match, my_user_id: int) -> int:
        """Вернуть user_id партнёра по мэтчу."""
        return match.user_b_id if match.user_a_id == my_user_id else match.user_a_id

    # ─── Сообщения чата ───────────────────────────────────────────────────

    async def get_active_chat(self, user_id: int) -> Optional[Match]:
        """Найти мэтч, в котором пользователь ведёт чат (самый свежий)."""
        result = await self.session.execute(
            select(Match).where(
                or_(Match.user_a_id == user_id, Match.user_b_id == user_id)
            ).order_by(Match.created_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def send_message(
        self, match_id: int, sender_id: int, body: str
    ) -> Message:
        """Отправить сообщение в чат мэтча."""
        msg = Message(
            match_id=match_id,
            sender_id=sender_id,
            body=body,
            sent_at=datetime.utcnow(),
        )
        self.session.add(msg)
        await self.session.flush()
        return msg

    async def get_messages(self, match_id: int, limit: int = 20) -> list[Message]:
        """Получить последние сообщения чата."""
        result = await self.session.execute(
            select(Message)
            .where(Message.match_id == match_id)
            .order_by(Message.sent_at.desc())
            .limit(limit)
        )
        return list(reversed(result.scalars().all()))

    # ─── Статистика ───────────────────────────────────────────────────────────

    async def get_user_stats(self, user_id: int) -> dict:
        """
        Агрегированная статистика пользователя.
        Возвращает dict с ключами:
          likes_sent, passes_sent, likes_received, matches, match_rate
        """
        likes_sent_res = await self.session.execute(
            select(func.count()).where(
                and_(Swipe.from_user_id == user_id, Swipe.action == "like")
            )
        )
        passes_sent_res = await self.session.execute(
            select(func.count()).where(
                and_(Swipe.from_user_id == user_id, Swipe.action == "pass")
            )
        )
        likes_received_res = await self.session.execute(
            select(func.count()).where(
                and_(Swipe.to_user_id == user_id, Swipe.action == "like")
            )
        )
        matches_res = await self.session.execute(
            select(func.count()).where(
                or_(Match.user_a_id == user_id, Match.user_b_id == user_id)
            )
        )

        likes_sent = likes_sent_res.scalar() or 0
        passes_sent = passes_sent_res.scalar() or 0
        likes_received = likes_received_res.scalar() or 0
        matches = matches_res.scalar() or 0
        match_rate = round(matches / likes_sent * 100, 1) if likes_sent > 0 else 0.0

        return {
            "likes_sent": likes_sent,
            "passes_sent": passes_sent,
            "likes_received": likes_received,
            "matches": matches,
            "match_rate": match_rate,
        }

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
