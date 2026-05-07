from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Настройки приложения, загружаются из .env файла."""

    # Telegram Bot
    bot_token: str

    # PostgreSQL
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "dating_bot"
    db_user: str = "postgres"
    db_password: str = "postgres"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # Celery (Redis DB 1 — брокер, DB 2 — бэкенд результатов)
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # Прокси для Telegram API (нужен при блокировке Telegram, например в РФ)
    # Пример: "http://user:pass@host:port" или "socks5://host:port"
    telegram_proxy: str | None = None

    # MinIO — объектное хранилище фотографий
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "dating-photos"
    minio_secure: bool = False  # True если HTTPS

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    class Config:
        env_file = ".env"


settings = Settings()
