"""
MinIO-хранилище фотографий профилей.

MinIO — S3-совместимое объектное хранилище. В проекте используется для
постоянного хранения фотографий: Telegram хранит фото у себя и отдаёт их по
file_id, но этот ID может стать недоступным со временем. MinIO служит
постоянным архивом, независимым от Telegram.

Принцип работы:
  1. Пользователь отправляет фото боту.
  2. Бот скачивает его с серверов Telegram (bot.download).
  3. Бот загружает байты в MinIO → получает storage_key (путь внутри bucket).
  4. В таблице profile_photos сохраняются и file_id, и storage_key.
  5. При показе профиля бот строит публичный URL к MinIO и отдаёт его Telegram
     для отображения — Telegram не зависит от своего кэша, фото берётся из MinIO.

Все операции с MinIO SDK (sync) выполняются через asyncio.to_thread(),
чтобы не блокировать event loop aiogram.
"""

import asyncio
import io
import logging
import uuid
from datetime import timedelta
from typing import Optional

from minio import Minio
from minio.error import S3Error

from app.config import settings

logger = logging.getLogger(__name__)


class MinIOStorage:
    """Обёртка над MinIO SDK с async-интерфейсом."""

    def __init__(self) -> None:
        self._client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        self._bucket = settings.minio_bucket

    # ─── Инициализация ────────────────────────────────────────────────────────

    async def ensure_bucket(self) -> None:
        """
        Создать bucket если он не существует.
        Вызывается один раз при старте бота.
        """
        def _sync():
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
                logger.info("MinIO: bucket '%s' создан.", self._bucket)
            else:
                logger.info("MinIO: bucket '%s' уже существует.", self._bucket)

        await asyncio.to_thread(_sync)

    # ─── Загрузка ─────────────────────────────────────────────────────────────

    async def upload_photo(
        self,
        data: bytes,
        content_type: str = "image/jpeg",
    ) -> str:
        """
        Загрузить байты фотографии в MinIO.

        Возвращает storage_key — путь объекта внутри bucket.
        Имя файла генерируется случайно (uuid4), чтобы избежать коллизий.

        Пример возвращаемого ключа: photos/3f7a2b1c4d5e.jpg
        """
        key = f"photos/{uuid.uuid4().hex}.jpg"

        def _sync():
            self._client.put_object(
                bucket_name=self._bucket,
                object_name=key,
                data=io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )

        await asyncio.to_thread(_sync)
        logger.debug("MinIO: загружено фото %s (%d байт)", key, len(data))
        return key

    # ─── Получение URL ────────────────────────────────────────────────────────

    def get_public_url(self, storage_key: str) -> str:
        """
        Вернуть публичный URL объекта.

        Работает только для bucket с политикой public-read
        (устанавливается командой `mc anonymous set public` в createbuckets).
        URL не имеет срока действия — подходит для отправки в Telegram.

        Пример: http://localhost:9000/dating-photos/photos/abc123.jpg
        """
        scheme = "https" if settings.minio_secure else "http"
        return f"{scheme}://{settings.minio_endpoint}/{self._bucket}/{storage_key}"

    async def get_presigned_url(self, storage_key: str, expires_seconds: int = 3600) -> str:
        """
        Вернуть временную подписанную ссылку (presigned URL) на объект.

        Работает с приватными bucket-ами. Ссылка действительна
        `expires_seconds` секунд (по умолчанию — 1 час).
        """
        def _sync():
            return self._client.presigned_get_object(
                bucket_name=self._bucket,
                object_name=storage_key,
                expires=timedelta(seconds=expires_seconds),
            )

        url = await asyncio.to_thread(_sync)
        return url

    # ─── Удаление ─────────────────────────────────────────────────────────────

    async def delete(self, storage_key: str) -> None:
        """Удалить объект из MinIO."""
        def _sync():
            self._client.remove_object(self._bucket, storage_key)

        await asyncio.to_thread(_sync)
        logger.debug("MinIO: удалён объект %s", storage_key)


# ─── Синглтон ─────────────────────────────────────────────────────────────────

_storage_instance: Optional[MinIOStorage] = None


def get_storage() -> Optional[MinIOStorage]:
    """
    Вернуть глобальный экземпляр MinIOStorage.
    Возвращает None если MinIO не сконфигурирован (MINIO_ENDPOINT пустой).
    """
    return _storage_instance


async def init_storage() -> Optional[MinIOStorage]:
    """
    Инициализировать хранилище при старте бота.
    При ошибке подключения — логирует и возвращает None (MinIO опционален).
    """
    global _storage_instance
    if not settings.minio_endpoint:
        logger.info("MinIO: MINIO_ENDPOINT не задан, хранилище отключено.")
        return None

    try:
        storage = MinIOStorage()
        await storage.ensure_bucket()
        _storage_instance = storage
        logger.info("MinIO: подключено к %s, bucket '%s'.", settings.minio_endpoint, settings.minio_bucket)
        return storage
    except S3Error as exc:
        logger.error("MinIO: ошибка при инициализации — %s", exc)
        return None
    except Exception as exc:
        logger.error("MinIO: не удалось подключиться — %s", exc)
        return None
