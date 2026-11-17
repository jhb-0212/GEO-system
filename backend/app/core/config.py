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
    # 告警风暴防护：同一时间窗内不同失败类（project_id + task_name + exception_type）最多逐类首报 N 类，超出只发一条汇总；0 表示不限流
    task_alert_max_per_window: int = 5
    task_alert_window_seconds: int = 300
    # 队列积压阈值：超过即 /health/queue 返回 503，供外部告警使用
    queue_backlog_threshold: int = 100
    celery_default_queue: str = "celery"
    evidence_local_root: str = ""  # 留空则用 backend/var/evidence
    # 监测采集：每引擎每分钟调用上限；0 或负数按 1 处理，避免无限流
    monitoring_engine_rate_limit_per_minute: int = 6
    # 网页端采集（浏览器登录态）风控更敏感：单独限速，默认 2 次/分钟
    monitoring_websearch_rate_limit_per_minute: int = 2
    # 网页端每日调用上限与限流冷却：触发后整引擎暂停，避免连续试探账号风控
    monitoring_websearch_daily_cap: int = 60
    monitoring_websearch_cooldown_minutes: int = 60
    # 网关内只重试适配器标记 retryable 的失败；Celery 任务级重试仍保留
    monitoring_gateway_max_attempts: int = 2
    monitoring_gateway_retry_backoff_seconds: float = 1.0
    # DeepSeek 网关估算费用（元/百万 token）；留空则不估算，只记 token
    deepseek_input_price_cny_per_million: float | None = None
    deepseek_output_price_cny_per_million: float | None = None
    # DeepSeek 网页版联网搜索：采集桥地址（留空则用入口自身的 entry_url）与单题超时
    deepseek_websearch_bridge_url: str = ""
    deepseek_websearch_timeout_seconds: float = 180.0

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
