"""配置集中管理：统一从仓库根目录 .env 读取，代码里不写密钥。"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]  # backend/
ROOT_DIR = BACKEND_DIR.parent  # geo-system/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 应用
    app_name: str = "GEO 系统 API"
    app_version: str = "0.1.0"
    app_env: str = "dev"
    api_base_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:3000"
    secret_key: str = "change-me-in-dev"

    # PostgreSQL
    database_url: str = "postgresql+psycopg://geo:geo_dev@localhost:5433/geo"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
