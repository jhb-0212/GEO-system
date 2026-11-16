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


class AccessTokenData(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class CurrentUserProjectData(BaseModel):
    id: str
    code: str
    name: str
    role_code: str
    permissions: list[str]


class CurrentUserData(BaseModel):
    id: str
    username: str
    display_name: str
    is_system_admin: bool
    projects: list[CurrentUserProjectData]


class KeywordData(BaseModel):
    id: str
    name: str
    category: str | None = None
    priority: int
    is_active: bool
    notes: str | None = None
    question_ids: list[str]
    content_version_ids: list[str]
    content_version_count: int
    created_at: datetime
    updated_at: datetime | None = None


class AuditLogData(BaseModel):
    id: str
    actor_id: str | None = None
    actor_name: str | None = None
    action: str
    target_type: str | None = None
    target_id: str | None = None
    created_at: datetime


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


class EngineEntryData(BaseModel):
    """入口配置：只暴露 credential_ref 与是否已配置，不返回任何密钥值。"""

    id: str
    engine_id: str
    entry_type: str
    name: str
    entry_url: str | None = None
    protocol: str
    model_name: str | None = None
    credential_ref: str | None = None
    credential_configured: bool
    supports_search: bool
    access_note: str | None = None
    last_verified_at: datetime | None = None
    is_active: bool


class EngineConnectionTestData(BaseModel):
    """测试连接结果：只返回诊断信息，不落样本、不回传回答正文。"""

    success: bool
    protocol: str
    endpoint: str | None = None
    model_name: str | None = None
    latency_ms: float | None = None
    error_code: str | None = None
    message: str
    checked_at: datetime


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


class ChannelAliasData(BaseModel):
    domain: str
    alias_name: str | None = None


class ChannelEditableData(ChannelData):
    """Fields required to reopen a saved channel in the edit form."""

    notes: str | None = None
    is_active: bool
    aliases: list[ChannelAliasData]


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


class ChannelDetailData(ChannelEditableData):
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


class QuestionData(BaseModel):
    id: str
    code: str
    title: str
    question_type: str
    audience: str | None = None
    intent: str | None = None
    priority: int
    status: str
    current_version_no: int
    current_text: str | None = None
    created_at: datetime
    updated_at: datetime


class QuestionCreated(BaseModel):
    id: str
    version_no: int


class QuestionVersionData(BaseModel):
    id: str
    question_id: str
    version_no: int
    text: str
    change_note: str | None = None
    created_by: str | None = None
    created_at: datetime


class QuestionVersionCreated(BaseModel):
    version_id: str
    version_no: int


class PlanData(BaseModel):
    id: str
    title: str
    plan_type: str
    status: str
    channel_id: str | None = None
    content_item_id: str | None = None
    site_page_id: str | None = None
    owner_id: str | None = None
    owner_name: str | None = None
    scheduled_at: datetime | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class PlanCreated(BaseModel):
    id: str


class QuoteData(BaseModel):
    id: str
    plan_id: str
    plan_title: str | None = None
    channel_id: str | None = None
    channel_name: str | None = None
    unit_price: float
    quantity: int
    currency: str
    budget: float
    status: str
    approved_by: str | None = None
    approved_by_name: str | None = None
    approved_at: datetime | None = None
    note: str | None = None
    created_at: datetime
    updated_at: datetime


class QuoteCreated(BaseModel):
    id: str
    status: str


class PageData(BaseModel):
    id: str
    slug: str
    title: str
    page_type: str
    url: str
    canonical_url: str | None = None
    publish_status: str
    content_item_id: str | None = None
    last_published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PageCreated(BaseModel):
    id: str
    slug: str


class MonitoringTaskData(BaseModel):
    id: str
    round_id: str
    status: str
    sampling_no: int
    question_code: str
    question_title: str
    engine_code: str
    engine_name: str
    created_at: datetime
    updated_at: datetime


class MonitoringSampleData(BaseModel):
    id: str
    task_id: str
    status: str
    attempt_no: int
    sampled_at: datetime | None = None
    raw_answer: str | None = None
    raw_response: dict[str, Any] | None = None
    brand_mentioned: bool | None = None
    failure_code: str | None = None
    failure_note: str | None = None
    review_result: str | None = None
    review_note: str | None = None
    reviewed_at: datetime | None = None


class MonitoringCitationData(BaseModel):
    id: str
    sample_id: str
    raw_url: str
    normalized_url: str | None = None
    domain: str | None = None
    channel_id: str | None = None
    channel_name: str | None = None
    channel_category: str | None = None
    is_brand_related: bool
    review_status: str
    review_note: str | None = None


class MonitoringSampleDetail(MonitoringSampleData):
    citations: list[MonitoringCitationData]


class UnknownDomainData(BaseModel):
    domain: str
    citation_count: int


class MonitoringRoundData(BaseModel):
    id: str
    seq: int
    name: str
    is_baseline: bool
    status: str
    planned_at: datetime | None = None
    created_at: datetime | None = None


class InactiveQuestionItem(BaseModel):
    id: str
    code: str
    title: str
    status: str


class BatchGenerateData(BaseModel):
    round_id: str
    requested_question_count: int
    eligible_question_count: int
    inactive_question_count: int
    inactive_question_ids: list[str]
    inactive_questions: list[InactiveQuestionItem]
    question_version_missing_count: int
    question_version_missing_question_ids: list[str]
    engine_count: int
    expected_task_count: int
    eligible_expected_task_count: int
    created_task_count: int
    reused_task_count: int
    generated_task_count: int
    complete: bool
    skipped_reason: str | None = None


class PublishAccountData(BaseModel):
    id: str
    account_name: str
    channel_id: str
    is_active: bool
    notes: str | None = None


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


class ContentVersionSubmitted(BaseModel):
    version_id: str
    status: str
    submitted_at: datetime


class ContentReviewQueueItem(BaseModel):
    version_id: str
    item_id: str
    title: str
    version_no: int
    status: str
    kind: str
    channel_id: str | None = None
    author_id: str | None = None
    author_name: str | None = None
    submitted_at: datetime | None = None


class ContentVersionDetail(BaseModel):
    version_id: str
    item_id: str
    title: str
    kind: str
    channel_id: str | None = None
    version_no: int
    status: str
    body: str
    content_hash: str
    change_note: str | None = None


class ContentReviewData(BaseModel):
    id: str
    version_id: str
    reviewer_id: str
    reviewer_name: str | None = None
    decision: str
    comment: str | None = None
    content_hash_snapshot: str
    created_at: datetime


class LeadCreated(BaseModel):
    id: str


class MemberChanged(BaseModel):
    member_id: str
    role_code: str | None = None


class MonitoringExecuted(BaseModel):
    task_id: str
    status: str


class SampleCitationItem(BaseModel):
    """样本详情内联的一条引用证据（B5 回看用，不重复返回完整回答）。"""

    citation_id: str
    raw_url: str
    normalized_url: str | None = None
    domain: str | None = None
    channel_id: str | None = None
    channel_name: str | None = None
    channel_category: str | None = None
    citation_usage: str | None = None
    is_brand_related: bool
    review_status: str


class SampleEvidenceItem(BaseModel):
    """样本关联的证据文件元信息；文件本体走 evidence download 端点。"""

    evidence_id: str
    file_type: str
    content_type: str | None = None
    byte_size: int | None = None
    checksum: str | None = None


class SampleDetailData(BaseModel):
    """样本回看详情（B5 GET）：原始回答 + 引用 + 证据文件元信息。"""

    id: str
    task_id: str
    attempt_no: int
    status: str
    sampled_at: datetime | None = None
    finished_at: datetime | None = None
    sampling_mode: str
    raw_answer: str | None = None
    brand_mentioned: bool | None = None
    engine_model: str | None = None
    model_version: str | None = None
    country_code: str | None = None
    language: str | None = None
    failure_code: str | None = None
    failure_note: str | None = None
    review_result: str | None = None
    review_note: str | None = None
    reviewed_at: datetime | None = None
    citations: list[SampleCitationItem]
    evidence_files: list[SampleEvidenceItem]


class SampleReviewData(BaseModel):
    """样本人工复核结果（B5 POST）。"""

    sample_id: str
    status: str
    review_result: str


class CitationData(BaseModel):
    """引用列表项（B6 GET / PATCH）。"""

    citation_id: str
    sample_id: str
    raw_url: str
    normalized_url: str | None = None
    domain: str | None = None
    citation_usage: str | None = None
    is_brand_related: bool
    review_status: str
    channel_id: str | None = None
    competitor_id: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None


class UnknownDomainItem(BaseModel):
    """未知域名待归类队列（B6 GET /unknown-domains）：review_pending 渠道维度，附引用覆盖计数。"""

    channel_id: str
    code: str
    name: str
    primary_domain: str | None = None
    citation_count: int
    sample_count: int
    last_sampled_at: datetime | None = None


class PublishAttemptCreated(BaseModel):
    attempt_id: str
    attempt_no: int
    task_status: str


class PublishTaskCreated(BaseModel):
    task_id: str
    status: str
    idempotency_key: str
    reused: bool


class PublishReceiptCreated(BaseModel):
    receipt_id: str
    task_id: str
    status: str


class PublishVerifyResult(BaseModel):
    task_id: str
    status: str


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


class GeoOverviewCounts(BaseModel):
    """GEO 验收指标的分子/分母，避免报告端只看比率无法复核。"""

    total_samples: int
    valid_answers: int
    brand_mentioned_answers: int
    failed_samples: int
    competitor_mentioned_samples: int
    citation_total: int
    brand_citations: int
    confirmed_brand_citations: int
    used_citations: int
    cited_citations: int
    active_questions: int
    covered_questions: int


class GeoCompetitorData(BaseModel):
    competitor: str
    mentioned_samples: int


class GeoDefinitionsData(BaseModel):
    valid_answers: str
    mention_rate: str
    citation_share: str
    sov: str
    prompt_coverage: str
    failure_rate: str
    freshness_hours: str


class StatsExcludedData(BaseModel):
    failed: int
    manual_review: int
    pending_or_running: int


class StatsOverviewData(BaseModel):
    valid_answers: int
    brand_mentioned_answers: int
    citation_answers: int
    brand_mention_rate: float | None = None
    citation_rate: float | None = None
    channel_count: int
    page_count: int
    excluded: StatsExcludedData


class StatsEngineData(BaseModel):
    engine_id: str
    engine_code: str
    engine_name: str
    valid_answers: int
    brand_mentioned_answers: int
    citation_answers: int
    brand_mention_rate: float | None = None
    citation_rate: float | None = None


class StatsQuestionData(BaseModel):
    question_id: str
    question_code: str
    question_title: str
    question_type: str
    valid_answers: int
    brand_mentioned_answers: int
    citation_answers: int
    brand_mention_rate: float | None = None
    citation_rate: float | None = None


class StatsTrendPoint(BaseModel):
    week_start: datetime
    valid_answers: int
    brand_mention_rate: float | None = None


class EngineTaskShare(BaseModel):
    engine_id: str
    engine_name: str
    task_count: int
    share: float


class GeoOverviewData(BaseModel):
    """内部验收口径：无有效回答时比率为 null，并带 statement 说明技术基线边界。"""

    valid_answers: int
    mention_rate: float | None = None
    citation_share: float | None = None
    sov: float | None = None
    prompt_coverage: float | None = None
    freshness_hours: float | None = None
    fresh_24h_rate: float | None = None
    failure_rate: float | None = None
    statement: str
    counts: GeoOverviewCounts
    by_competitor: list[GeoCompetitorData]
    definitions: GeoDefinitionsData


def ok(payload: Any) -> dict[str, Any]:
    return {"data": payload}


def ok_page(payload: Any, *, page: int, page_size: int, total: int) -> dict[str, Any]:
    return {"data": payload, "meta": {"page": page, "page_size": page_size, "total": total}}
