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
    app_version: str = "1.0.0"
    app_env: str = "dev"
    api_base_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:3000"
    secret_key: str = "change-me-in-dev"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    # 导出与证据文件：同步导出有行数上限，超过必须走异步任务
    export_sync_row_limit: int = 5000
    log_level: str = "INFO"
    # 任务失败告警：留空则只写 JSON 错误日志，不外部推送
    task_alert_webhook: str = ""
    # 告警风暴防护：同一时间窗内最多逐条推送 N 条，超出只发一条汇总；0 表示不限流
    task_alert_max_per_window: int = 5
    task_alert_window_seconds: int = 300
    # 队列积压阈值：超过即 /health/queue 返回 503，供外部告警使用
    queue_backlog_threshold: int = 100
    celery_default_queue: str = "celery"
    evidence_local_root: str = ""  # 留空则用 backend/var/evidence
    # 监测采集：每引擎每分钟调用上限；0 或负数按 1 处理，避免无限流
    monitoring_engine_rate_limit_per_minute: int = 6

    # PostgreSQL
    database_url: str = "postgresql+psycopg://geo:geo_dev@localhost:5433/geo"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def evidence_root(self) -> Path:
        """证据文件本地根目录：只允许从这里往下读，防止路径穿越。"""
        raw = self.evidence_local_root.strip()
        path = Path(raw) if raw else BACKEND_DIR / "var" / "evidence"
        return path if path.is_absolute() else ROOT_DIR / path


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
