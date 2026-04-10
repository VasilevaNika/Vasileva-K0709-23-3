from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,  # поставь True для отладки SQL-запросов
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db_session() -> AsyncSession:
    """Зависимость для получения сессии БД."""
    async with async_session_factory() as session:
        yield session


async def init_db():
    """Создание всех таблиц при старте (для разработки)."""
    async with engine.begin() as conn:
        # Импортируем модели, чтобы они были зарегистрированы в Base.metadata
        import app.models  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)
