"""配置集中管理：统一从仓库根目录 .env 读取，代码里不写密钥。"""

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]  # backend/
ROOT_DIR = BACKEND_DIR.parent  # geo-system/

DEV_ENVS = frozenset({"dev", "local", "test"})
DEV_SECRET_KEY = "change-me-in-dev"


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
    cors_origins: str = (
        "http://localhost:3000,http://localhost:3001,"
        "http://127.0.0.1:3000,http://127.0.0.1:3001"
    )
    secret_key: str = "change-me-in-dev"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    # 登录失败限流：同一账号 / 同一来源 IP 的分钟与小时窗口，超限返回 429
    login_rate_limit_per_minute: int = 5
    login_rate_limit_per_hour: int = 20
    # 信任的反代层数：0 表示不信任 X-Forwarded-For；生产 Nginx 前置时设为 1
    trusted_proxy_count: int = 0
    # openai_compatible 入口额外允许的 host（逗号分隔，仅部署方维护）
    engine_allowed_hosts: str = ""

    # 导出与证据文件：同步导出有行数上限，超过必须走异步任务
    export_sync_row_limit: int = 5000
    # 公开只读接口（FAQ）按来源 IP 的每分钟额度；<=0 表示关闭限流
    public_faq_per_minute: int = 30
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
    # S3 兼容对象存储：四项齐全时证据文件自动走对象存储，否则回退 evidence_local_root
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "geo-evidence"
    s3_region: str = "us-east-1"
    s3_secure: bool = False
    # 监测采集：每引擎每分钟调用上限；0 或负数按 1 处理，避免无限流
    monitoring_engine_rate_limit_per_minute: int = 6
    # 网页端采集（浏览器登录态）风控更敏感：稳跑口径 1 次/分钟、日 20 条、单轮 5 条
    monitoring_websearch_rate_limit_per_minute: int = 1
    monitoring_websearch_daily_cap: int = 20
    monitoring_websearch_round_cap: int = 5
    # 任务执行租约：超过该时长未落终态视为失联，由调度器回收
    monitoring_task_lease_seconds: int = 900
    # Outbox 投递失败上限：达到后事件置 FAILED（死信），退出投递批次
    outbox_max_failures: int = 10
    # 命中一次限流即当天停手：冷却 24 小时，期间整引擎拒采
    monitoring_websearch_cooldown_minutes: int = 1440
    # 网关内只重试适配器标记 retryable 的失败；Celery 任务级重试仍保留
    monitoring_gateway_max_attempts: int = 2
    monitoring_gateway_retry_backoff_seconds: float = 1.0
    # DeepSeek 网关估算费用（元/百万 token）；留空则不估算，只记 token
    deepseek_input_price_cny_per_million: float | None = None
    deepseek_output_price_cny_per_million: float | None = None

    # PostgreSQL
    database_url: str = "postgresql+psycopg://geo:geo_dev@localhost:5433/geo"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    @model_validator(mode="after")
    def _reject_dev_secret_in_production(self) -> "Settings":
        """非开发环境拒绝默认/过短 SECRET_KEY，避免用公开默认值签发 JWT。"""
        if self.app_env.strip().lower() in DEV_ENVS:
            return self
        secret = self.secret_key.strip()
        if secret in {"", DEV_SECRET_KEY} or len(secret) < 32:
            raise ValueError(
                f"app_env={self.app_env} 时必须配置 SECRET_KEY（至少 32 位，且不能使用默认值）"
            )
        return self

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
