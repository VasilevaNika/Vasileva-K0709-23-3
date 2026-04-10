from datetime import datetime, date

from sqlalchemy import (
    BigInteger, Integer, String, Text, Boolean, Date, Float,
    DateTime, ForeignKey, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    """Учётная запись пользователя."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_registered: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    profile: Mapped["Profile | None"] = relationship(back_populates="user", uselist=False)
    preferences: Mapped["UserPreferences | None"] = relationship(back_populates="user", uselist=False)
    sent_swipes: Mapped[list["Swipe"]] = relationship(
        back_populates="from_user", foreign_keys="Swipe.from_user_id"
    )
    received_swipes: Mapped[list["Swipe"]] = relationship(
        back_populates="to_user", foreign_keys="Swipe.to_user_id"
    )
    ratings: Mapped["ProfileRating | None"] = relationship(back_populates="user", uselist=False)

    def __repr__(self):
        return f"<User telegram_id={self.telegram_id}>"


class Profile(Base):
    """Анкета пользователя."""
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), unique=True, nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    bio: Mapped[str | None] = mapped_column(Text, default=None)
    birth_date: Mapped[date | None] = mapped_column(Date, default=None)
    gender: Mapped[str | None] = mapped_column(String(20), default=None)
    city: Mapped[str | None] = mapped_column(String(100), default=None)
    interests: Mapped[str | None] = mapped_column(Text, default=None)
    profile_completeness: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="profile")
    photos: Mapped[list["ProfilePhoto"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Profile {self.display_name} (user_id={self.user_id})>"


class ProfilePhoto(Base):
    """Фотографии профиля."""
    __tablename__ = "profile_photos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("profiles.id"), nullable=False)
    file_id: Mapped[str] = mapped_column(String(200), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(500), default=None)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    profile: Mapped["Profile"] = relationship(back_populates="photos")

    def __repr__(self):
        return f"<Photo id={self.id} profile_id={self.profile_id}>"


class UserPreferences(Base):
    """Предпочтения пользователя (кого ищет)."""
    __tablename__ = "user_preferences"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), primary_key=True
    )
    preferred_gender: Mapped[str | None] = mapped_column(String(20), default=None)
    age_min: Mapped[int | None] = mapped_column(Integer, default=None)
    age_max: Mapped[int | None] = mapped_column(Integer, default=None)
    preferred_city: Mapped[str | None] = mapped_column(String(100), default=None)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="preferences")

    def __repr__(self):
        return f"<Preferences user_id={self.user_id}>"


class Swipe(Base):
    """Действие свайпа (лайк/пас)."""
    __tablename__ = "swipes"
    __table_args__ = (
        UniqueConstraint("from_user_id", "to_user_id", name="uq_swipe_pair"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    from_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    to_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)  # 'like' | 'pass'
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    from_user: Mapped["User"] = relationship(
        back_populates="sent_swipes", foreign_keys=[from_user_id]
    )
    to_user: Mapped["User"] = relationship(
        back_populates="received_swipes", foreign_keys=[to_user_id]
    )

    def __repr__(self):
        return f"<Swipe {self.action}: {self.from_user_id} -> {self.to_user_id}>"


class Match(Base):
    """Взаимный лайк (мэтч)."""
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_a_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    user_b_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Match {self.user_a_id} <-> {self.user_b_id}>"


class Message(Base):
    """Сообщение в чате мэтча."""
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("matches.id"), nullable=False)
    sender_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Message match_id={self.match_id} sender_id={self.sender_id}>"


class ProfileRating(Base):
    """Кэш оценок профиля."""
    __tablename__ = "profile_ratings"

    profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("profiles.id"), primary_key=True
    )
    primary_score: Mapped[float] = mapped_column(Float, default=0.0)
    behavior_score: Mapped[float] = mapped_column(Float, default=0.0)
    combined_score: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="ratings", foreign_keys="ProfileRating.profile_id")

    def __repr__(self):
        return f"<Rating profile_id={self.profile_id} combined={self.combined_score}>"
