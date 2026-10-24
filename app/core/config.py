"""应用配置：全部来自环境变量，本地开发时自动读取 .env。"""

from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "ai-services-backend"
    app_version: str = "0.1.0"
    environment: Literal["local", "docker", "test", "production"] = "local"
    debug: bool = False

    log_level: str = "INFO"
    log_json: bool = False

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "app"
    postgres_password: str = "app"
    postgres_db: str = "app"
    db_pool_size: int = 10
    db_echo: bool = False
    db_connect_timeout: float = 3.0

    redis_url: str = "redis://localhost:6379/0"
    redis_timeout: float = 2.0

    rate_limit_per_minute: int = 60
    rate_limit_window_seconds: int = 60
    idempotency_ttl_seconds: int = 86400

    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "app"
    rabbitmq_password: str = "app"

    @property
    def async_database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{quote_plus(self.postgres_user)}:"
            f"{quote_plus(self.postgres_password)}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_database_url(self) -> str:
        return (
            f"postgresql+psycopg://{quote_plus(self.postgres_user)}:"
            f"{quote_plus(self.postgres_password)}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def broker_url(self) -> str:
        return (
            f"amqp://{quote_plus(self.rabbitmq_user)}:"
            f"{quote_plus(self.rabbitmq_password)}@"
            f"{self.rabbitmq_host}:{self.rabbitmq_port}//"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
