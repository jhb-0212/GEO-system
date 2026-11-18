"""官网诊断与访问观测的请求/响应模型。"""

from datetime import datetime

from pydantic import BaseModel, Field


class CrawlerEventCreate(BaseModel):
    page_url: str = Field(min_length=1, max_length=2048)
    ua_claimed: str | None = Field(default=None, max_length=512)
    source_ip: str | None = Field(default=None, max_length=64)
    verified_bot: bool = False
    http_status: int | None = Field(default=None, ge=100, le=599)
    bytes: int | None = Field(default=None, ge=0)
    occurred_at: datetime
    import_source: str | None = Field(default=None, max_length=64)


class TrafficEventCreate(BaseModel):
    visitor_session_id: str | None = Field(default=None, max_length=64)
    landing_url: str = Field(min_length=1, max_length=2048)
    utm_source: str | None = Field(default=None, max_length=128)
    utm_campaign: str | None = Field(default=None, max_length=128)
    referrer: str | None = Field(default=None, max_length=2048)
    is_bot: bool = False
    occurred_at: datetime
    import_source: str | None = Field(default=None, max_length=64)


class CrawlerEventImport(BaseModel):
    events: list[CrawlerEventCreate] = Field(min_length=1, max_length=5000)
    source: str | None = Field(default=None, max_length=64)


class TrafficEventImport(BaseModel):
    events: list[TrafficEventCreate] = Field(min_length=1, max_length=5000)
    source: str | None = Field(default=None, max_length=64)


class PageCheckResult(BaseModel):
    id: str
    url: str
    canonical_url: str | None
    robots_allowed: bool | None
    in_sitemap: bool | None
    canonical_ok: bool | None
    http_status: int | None
    js_dependent: bool | None
    checked_at: datetime
    check_error: str | None


class CrawlerEventImportResult(BaseModel):
    imported: int
    matched_pages: int


class TrafficEventImportResult(BaseModel):
    imported: int


class SiteDiagnosticsSummary(BaseModel):
    pages_total: int
    pages_checked: int
    robots_blocked: int
    not_in_sitemap: int
    canonical_bad: int
    http_error: int
    js_dependent: int
    crawler_events: int
    verified_bot_events: int
    crawled_pages: int
    traffic_events: int
    bot_traffic_events: int
    visitor_sessions: int
    leads_with_session: int
    buckets: dict[str, int]
