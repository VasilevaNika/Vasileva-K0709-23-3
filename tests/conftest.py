"""
Общие фикстуры для всех тестов.

Вместо реального PostgreSQL используется SQLite in-memory через aiosqlite —
это позволяет запускать тесты без запущенного сервера базы данных.
StaticPool гарантирует, что все операции внутри одного теста используют
одно и то же in-memory соединение (иначе каждое новое подключение SQLite
создаёт новую пустую БД).

Вместо реального Redis используется fakeredis — библиотека, которая
полностью эмулирует Redis API в памяти процесса.
"""

import os

# BOT_TOKEN обязателен в pydantic-settings; ставим заглушку до первого импорта app.*
os.environ.setdefault("BOT_TOKEN", "test_token_not_real")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/1")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.models  # noqa: F401 — регистрирует все модели в Base.metadata


# SQLite не поддерживает autoincrement для BIGINT (только для INTEGER).
# Этот компилятор заменяет BIGINT на INTEGER при генерации DDL для SQLite,
# что позволяет использовать те же модели, что и для PostgreSQL.
@compiles(BigInteger, "sqlite")
def _bigint_as_integer_on_sqlite(type_, compiler, **kwargs):
    return "INTEGER"

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_engine():
    """Создаёт чистый движок SQLite in-memory для одного теста."""
    engine = create_async_engine(
        TEST_DB_URL,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Открытая AsyncSession для одного теста; откатывается после теста."""
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
