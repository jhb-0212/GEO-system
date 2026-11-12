"""统一响应封装与响应模型。

成功响应统一是 `{"data": ...}`，错误信封统一是 `{"error": {"code", "message"}}`。
这里同时定义 OpenAPI 用的响应模型：路由上挂 `response_model` 后，`docs/openapi.json`
才能导出真实字段，前端可据此生成类型与 mock（此前 schema 全是空 object）。
"""

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    """成功响应信封。"""

    data: T


class PageMeta(BaseModel):
    """分页元信息，与契约 1.3 一致。"""

    page: int
    page_size: int
    total: int


class PagedEnvelope(BaseModel, Generic[T]):
    """分页列表响应：`{"data": [...], "meta": {"page", "page_size", "total"}}`。"""

    data: list[T]
    meta: PageMeta


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorEnvelope(BaseModel):
    """错误响应信封，与 `main.py` 的异常处理器一致。"""

    error: ErrorBody


# 业务路由统一声明的错误响应：认证失败、越权、资源不存在、状态冲突
COMMON_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorEnvelope, "description": "未认证或令牌无效"},
    403: {"model": ErrorEnvelope, "description": "越权：项目未授权或能力不足"},
    404: {"model": ErrorEnvelope, "description": "资源不存在（不区分是否越权）"},
    409: {"model": ErrorEnvelope, "description": "状态冲突，任务被拒绝"},
    422: {"model": ErrorEnvelope, "description": "请求参数校验失败（code=validation_error）"},
}


class TaskStatusData(BaseModel):
    """统一任务状态（来源 outbox_events），字段对齐契约 1.5。

    `progress` / `finished_at` 当前无数据源（outbox 只记录状态与错误描述），返回 null，
    已在契约变更单 CR-001 中标注，待执行器落库进度后补齐。
    """

    task_id: str
    kind: str
    project_id: str | None = None
    topic: str
    status: str
    progress: dict[str, Any] | None = None
    error: str | None = None
    finished_at: datetime | None = None
    created_at: datetime
    dispatched_at: datetime | None = None


class EngineData(BaseModel):
    id: str
    code: str
    name: str
    vendor: str
    is_active: bool


class ProjectData(BaseModel):
    id: str
    code: str
    name: str
    status: str


class MemberData(BaseModel):
    member_id: str
    user_id: str
    role_code: str | None = None
    is_active: bool


class ChannelData(BaseModel):
    id: str
    code: str
    name: str
    category: str | None = None
    status: str
    primary_domain: str | None = None


class ChannelCitationData(BaseModel):
    """渠道明细中的一条引用证据，字段只读、不返回完整原始回答。"""

    citation_id: str
    sample_id: str
    task_id: str
    engine_code: str
    engine_name: str
    question_code: str
    sample_status: str
    sampled_at: datetime | None = None
    raw_url: str
    normalized_url: str | None = None
    domain: str | None = None
    is_brand_related: bool
    review_status: str
    brand_mentioned: bool | None = None
    failure_code: str | None = None
    answer_excerpt: str | None = None


class ChannelDetailData(ChannelData):
    """渠道详情：基础台账 + 引用覆盖摘要 + 逐条引用（用于“从渠道数点开明细”）。"""

    citation_count: int
    sample_count: int
    page_count: int
    page_urls: list[str]
    engine_codes: list[str]
    question_codes: list[str]
    first_sampled_at: datetime | None = None
    last_sampled_at: datetime | None = None
    citations: list[ChannelCitationData]


class LeadData(BaseModel):
    id: str
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_wechat: str | None = None
    interested_course: str | None = None
    enrollment_status: str | None = None
    lead_source: str | None = None
    source_question_id: str | None = None
    source_channel_id: str | None = None
    source_engine_id: str | None = None
    landing_url: str | None = None
    utm_campaign: str | None = None


class MonitoringTaskData(BaseModel):
    id: str
    round_id: str
    status: str
    sampling_no: int


class PublishTaskData(BaseModel):
    id: str
    status: str
    channel_id: str
    version_id: str


class ContentItemCreated(BaseModel):
    item_id: str


class ContentVersionCreated(BaseModel):
    version_id: str
    version_no: int


class ContentBodyUpdated(BaseModel):
    version_id: str
    content_hash: str


class ContentReviewCreated(BaseModel):
    review_id: str
    decision: str


class LeadCreated(BaseModel):
    id: str


class MemberChanged(BaseModel):
    member_id: str
    role_code: str | None = None


class MonitoringExecuted(BaseModel):
    task_id: str
    status: str


class PublishAttemptCreated(BaseModel):
    attempt_id: str
    attempt_no: int
    task_status: str


class HealthData(BaseModel):
    status: str
    service: str
    env: str


class HealthDbData(BaseModel):
    status: str
    database: str
    detail: str | None = None


class HealthRedisData(BaseModel):
    status: str
    redis: str
    detail: str | None = None


class WorkerHeartbeatData(BaseModel):
    name: str
    last_seen_seconds: int
    healthy: bool


class HealthWorkerData(BaseModel):
    status: str
    worker: str
    stale_after_seconds: int
    workers: list[WorkerHeartbeatData] = []
    detail: str | None = None


class HealthQueueData(BaseModel):
    status: str
    queue: str
    depth: int
    threshold: int
    detail: str | None = None


def ok(payload: Any) -> dict[str, Any]:
    return {"data": payload}


def ok_page(payload: Any, *, page: int, page_size: int, total: int) -> dict[str, Any]:
    return {"data": payload, "meta": {"page": page, "page_size": page_size, "total": total}}
