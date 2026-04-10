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

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    class Config:
        env_file = ".env"


settings = Settings()
