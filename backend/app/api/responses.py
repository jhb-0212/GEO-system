"""统一响应封装与响应模型。

成功响应统一是 `{"data": ...}`，错误信封统一是 `{"error": {"code", "message"}}`。
这里同时定义 OpenAPI 用的响应模型：路由上挂 `response_model` 后，`docs/openapi.json`
才能导出真实字段，前端可据此生成类型与 mock（此前 schema 全是空 object）。
"""

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

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
    serial_no: int
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
    # 密钥来源：database（系统内填写，加密落库）/ environment（服务器环境变量）/ none
    credential_source: str | None = None
    credential_updated_at: datetime | None = None
    config_redacted: bool = False
    supports_search: bool
    supports_citation: bool = False
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
    owner_name: str | None = None
    priority: int = 3
    business_confirmed_at: datetime | None = None
    business_confirmed_by: str | None = None
    updated_at: datetime | None = None
    channel_count: int = 0
    task_count: int = 0


class MemberData(BaseModel):
    member_id: str
    user_id: str
    username: str | None = None
    display_name: str | None = None
    email: str | None = None
    role_code: str | None = None
    is_active: bool


class UserCandidateData(BaseModel):
    id: str
    username: str
    display_name: str
    email: str | None = None


class CompetitorData(BaseModel):
    id: str
    name: str
    domain: str | None = None
    is_active: bool
    notes: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class CompetitorCreated(BaseModel):
    id: str


class BrandProfileData(BaseModel):
    """品牌口径配置 + 生效词表；`configured=false` 时表示仍在用项目名回退。"""

    configured: bool
    canonical_name: str | None = None
    aliases: list[str] = []
    identifiers: list[str] = []
    owned_domains: list[str] = []
    notes: str | None = None
    is_active: bool = False
    updated_at: datetime | None = None
    effective_mention_terms: list[str] = []
    effective_identifier_terms: list[str] = []
    effective_owned_domains: list[str] = []


class BrandGovernanceOwnerData(BaseModel):
    name: str
    contact: str | None = None
    channels: int


class BrandGovernanceData(BaseModel):
    """首月运营准备度：域名、品牌口径、素材、渠道负责人是否都落到系统里。"""

    configured: bool
    domains: list[str]
    mention_terms: int
    identifier_terms: int
    materials_total: int
    materials_by_category: dict[str, int]
    channels_total: int
    channels_with_owner: int
    channel_owners: list[BrandGovernanceOwnerData]
    ready: bool
    missing: list[str]


class MetricDefinitionData(BaseModel):
    id: str
    code: str
    name: str
    rule_version: int
    formula: str
    description: str | None = None
    effective_from: datetime
    effective_to: datetime | None = None
    status: str
    created_at: datetime
    updated_at: datetime | None = None


class MetricDefinitionCreated(BaseModel):
    id: str
    rule_version: int


class ChannelData(BaseModel):
    id: str
    code: str
    name: str
    category: str | None = None
    status: str
    approval_status: str = "pending_review"
    primary_domain: str | None = None
    publish_url: str | None = None
    login_url: str | None = None
    owner_name: str | None = None
    owner_contact: str | None = None


class ChannelAliasData(BaseModel):
    domain: str
    alias_name: str | None = None


class ChannelApprovalData(BaseModel):
    """一条渠道准入审批周期：提交人/审批人/时间/结论/意见。"""

    id: str
    submitted_by: str | None = None
    submitted_by_name: str | None = None
    submitted_at: datetime | None = None
    reviewed_by: str | None = None
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None = None
    decision: str | None = None
    comment: str | None = None
    created_at: datetime | None = None


class ChannelEditableData(ChannelData):
    """Fields required to reopen a saved channel in the edit form."""

    notes: str | None = None
    is_active: bool
    aliases: list[ChannelAliasData]
    submitted_by: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    decision_comment: str | None = None


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
    """渠道详情：基础台账 + 引用覆盖摘要 + 逐条引用（用于“从渠道数点开明细”）。

    `citation_count` 是发布回执 URL 归因，代表渠道效果；`observed_*` 是域名观测
    （人工确认引用命中主域名/别名），只用于信源层排查，不参与渠道效果与 `channel_count`。
    """

    citation_count: int
    sample_count: int
    page_count: int
    citation_page: int = 1
    citation_page_size: int = 20
    page_urls: list[str]
    engine_codes: list[str]
    question_codes: list[str]
    first_sampled_at: datetime | None = None
    last_sampled_at: datetime | None = None
    citations: list[ChannelCitationData]
    approvals: list[ChannelApprovalData] = []
    observed_domain_count: int = 0
    observed_citation_count: int = 0
    observed_sample_count: int = 0
    observed_page_count: int = 0
    observed_page_urls: list[str] = Field(default_factory=list)
    observed_engine_codes: list[str] = Field(default_factory=list)
    observed_question_codes: list[str] = Field(default_factory=list)
    observed_citations: list[ChannelCitationData] = Field(default_factory=list)


class ChannelApprovalListData(BaseModel):
    approvals: list[ChannelApprovalData]


class ChannelAnomalyData(BaseModel):
    """一条渠道/发布回执一致性异常。"""

    code: str
    severity: str
    channel_id: str
    channel_code: str
    channel_name: str
    channel_status: str
    task_id: str | None = None
    task_status: str | None = None
    receipt_id: str | None = None
    published_url: str | None = None
    message: str
    recommended_action: str
    task_updated_at: datetime | None = None
    receipt_received_at: datetime | None = None


class ChannelAnomalyCounts(BaseModel):
    total: int
    high: int
    warning: int


class ChannelAnomalyListData(BaseModel):
    """渠道异常清单：看板顶部提示和逐条处理依据。"""

    generated_at: datetime
    counts: ChannelAnomalyCounts
    anomalies: list[ChannelAnomalyData]


class LeadData(BaseModel):
    id: str
    serial_no: int
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_wechat: str | None = None
    interested_course: str | None = None
    reported_ai_product: str | None = None
    is_valid: bool = True
    enrollment_status: str | None = None
    lead_source: str | None = None
    source_question_id: str | None = None
    source_channel_id: str | None = None
    source_engine_id: str | None = None
    landing_url: str | None = None
    session_id: str | None = None
    utm_campaign: str | None = None
    note: str | None = None
    owner_id: str | None = None
    owner_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class LeadStatusCountsData(BaseModel):
    unknown: int
    contacted: int
    enrolled: int
    lost: int


class LeadFunnelStageData(BaseModel):
    """漏斗阶段：rate 相对总量，step_rate 相对上一阶段。"""

    key: str
    label: str
    count: int
    rate: float | None = None
    step_rate: float | None = None


class LeadFunnelGroupData(BaseModel):
    key: str
    label: str
    total: int
    valid: int
    contacted: int
    enrolled: int


class AiAttributionData(BaseModel):
    """官网访问与来源口径：机器、可追踪访问、监测引用、自报/引擎来源分别计数。"""

    crawler_events: int
    verified_bot_events: int
    human_visits: int
    trackable_visits: int
    human_sessions: int
    monitored_citations: int
    monitored_citation_urls: int
    self_reported_ai_leads: int
    engine_attributed_leads: int
    self_reported_ai_valid_leads: int


class LeadFunnelData(BaseModel):
    """线索漏斗：咨询 → 有效 → 已联系 → 已报名，并带来源/渠道/题目归因。"""

    start_at: datetime | None = None
    end_at: datetime | None = None
    total: int
    valid: int
    contacted: int
    enrolled: int
    lost: int
    status_counts: LeadStatusCountsData
    contact_rate: float | None = None
    conversion_rate: float | None = None
    stages: list[LeadFunnelStageData]
    ai_attribution: AiAttributionData
    by_source: list[LeadFunnelGroupData]
    by_channel: list[LeadFunnelGroupData]
    by_question: list[LeadFunnelGroupData]


class FaqData(BaseModel):
    id: str
    project_id: str
    question: str
    answer: str
    category: str | None = None
    status: str
    sort_order: int
    deleted_at: datetime | None = None
    deleted_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PublicFaqData(BaseModel):
    """公开接口专用：不带 project_id、status、deleted_at/deleted_by 等内部字段。"""

    id: str
    question: str
    answer: str
    category: str | None = None
    sort_order: int
    updated_at: datetime | None = None


class FaqCreated(BaseModel):
    id: str


class MaterialData(BaseModel):
    id: str
    project_id: str
    title: str
    category: str
    description: str | None = None
    file_name: str
    content_type: str | None = None
    byte_size: int
    checksum: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


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
    question_type: str | None = None
    audience: str | None = None
    intent: str | None = None
    priority: int | None = None
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


class OpportunityData(BaseModel):
    id: str
    title: str
    gap_type: str
    status: str
    question_id: str | None = None
    sample_id: str | None = None
    evidence_refs: list[dict] = []
    score_factors: dict[str, int]
    score_weights: dict[str, float]
    priority_score: float
    owner_id: str | None = None
    owner_name: str | None = None
    linked_content_plan_id: str | None = None
    linked_content_item_id: str | None = None
    linked_publish_task_id: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


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


class BudgetApprovalData(BaseModel):
    id: str
    category: str
    title: str
    quantity: float | None = None
    unit: str | None = None
    unit_price: float | None = None
    amount: float
    currency: str
    status: str
    requested_by: str | None = None
    requested_by_name: str | None = None
    approved_by: str | None = None
    approved_by_name: str | None = None
    approved_at: datetime | None = None
    note: str | None = None
    decision_note: str | None = None
    created_at: datetime
    updated_at: datetime


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
    robots_allowed: bool | None = None
    in_sitemap: bool | None = None
    canonical_ok: bool | None = None
    http_status: int | None = None
    js_dependent: bool | None = None
    checked_at: datetime | None = None
    check_error: str | None = None
    created_at: datetime
    updated_at: datetime


class PageCreated(BaseModel):
    id: str
    slug: str


class MonitoringTaskData(BaseModel):
    id: str
    serial_no: int
    round_id: str
    status: str
    sampling_no: int
    question_code: str
    question_title: str
    engine_code: str
    engine_name: str
    trace_id: str | None = None
    created_at: datetime
    updated_at: datetime


class MonitoringSampleData(BaseModel):
    id: str
    serial_no: int
    task_id: str
    trace_id: str | None = None
    status: str
    attempt_no: int
    sampled_at: datetime | None = None
    conversation_id: str | None = None
    conversation_mode: str | None = None
    answer_excerpt: str | None = None
    raw_answer: str | None = None
    raw_response: dict[str, Any] | None = None
    request_payload: dict[str, Any] | None = None
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost_cny: float | None = None
    gateway_version: str | None = None
    brand_mentioned: bool | None = None
    failure_code: str | None = None
    failure_note: str | None = None
    review_result: str | None = None
    review_note: str | None = None
    reviewed_at: datetime | None = None
    evidence_count: int = 0


class SampleEvidenceCoverageData(BaseModel):
    total_samples: int
    samples_with_evidence: int
    samples_missing_evidence: int
    coverage_rate: float | None = None
    missing_sample_ids: list[str]
    missing_truncated: bool = False


class MonitoringCitationData(BaseModel):
    id: str
    sample_id: str
    trace_id: str | None = None
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


class MonitoringRoundCompleteData(BaseModel):
    """轮次完成结果：状态迁移与统计快照同事务落库。"""

    round: MonitoringRoundData
    snapshot_id: str
    snapshot_hash: str
    captured_at: datetime
    rule_version: str
    task_counts: dict[str, int]


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
    task_count: int = 0


class OAuthProviderData(BaseModel):
    code: str
    name: str
    scopes: list[str]


class OAuthAuthorizeData(BaseModel):
    authorization_url: str
    state: str
    expires_at: datetime


class OAuthConnectionData(BaseModel):
    id: str
    provider_code: str
    provider_name: str
    channel_id: str | None = None
    external_account_id: str
    external_account_name: str | None = None
    external_account_email: str | None = None
    scopes: list[str]
    status: str
    has_refresh_token: bool
    expires_at: datetime | None = None
    connected_at: datetime | None = None
    last_refreshed_at: datetime | None = None
    revoked_at: datetime | None = None


class PublishTaskData(BaseModel):
    id: str
    serial_no: int
    status: str
    channel_id: str
    account_id: str | None = None
    account_name: str | None = None
    version_id: str
    version_no: int
    version_title: str | None = None
    trace_id: str | None = None


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
    status_label: str
    kind: str
    channel_id: str | None = None
    author_id: str | None = None
    author_name: str | None = None
    submitted_at: datetime | None = None


class ContentFactLinkData(BaseModel):
    """内容版本关联事实的当前状态；warning 非空时审批会被拦截。"""

    fact_id: str
    fact_type: str
    fact_key: str
    fact_value: str
    approval_status: str
    current_version_no: int
    linked_version_no: int
    stale: bool
    warning: str | None = None


class ContentVersionDetail(BaseModel):
    version_id: str
    item_id: str
    title: str
    kind: str
    channel_id: str | None = None
    version_no: int
    status: str
    status_label: str
    body: str
    content_hash: str
    change_note: str | None = None
    question_ids: list[str] = []
    citation_ids: list[str] = []
    fact_ids: list[str] = []
    fact_links: list[ContentFactLinkData] = []


class ContentExportPackage(BaseModel):
    """交付包：可直接粘进公司官网 CMS 的成品字段（geo 不渲染页面）。"""

    version_id: str
    item_id: str
    title: str
    slug_suggestion: str
    version_no: int
    status: str
    content_hash: str
    markdown: str
    html: str
    meta_description: str
    canonical_hint: str | None = None
    jsonld: list[dict[str, Any]]
    checklist: list[str]


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
    serial_no: int


class MemberChanged(BaseModel):
    member_id: str
    role_code: str | None = None


class MonitoringExecuted(BaseModel):
    task_id: str
    status: str


class SampleCitationItem(BaseModel):
    """样本详情内联的一条引用证据（B5 回看用，不重复返回完整回答）。"""

    citation_id: str
    trace_id: str | None = None
    raw_url: str
    normalized_url: str | None = None
    domain: str | None = None
    title: str | None = None
    position: int | None = None
    source_category: str | None = None
    page_type: str | None = None
    classification_source: str | None = None
    classification_rule_version: str | None = None
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
    serial_no: int
    task_id: str
    trace_id: str | None = None
    attempt_no: int
    status: str
    sampled_at: datetime | None = None
    finished_at: datetime | None = None
    sampling_mode: str
    conversation_id: str
    conversation_mode: str
    raw_answer: str | None = None
    request_payload: dict[str, Any] | None = None
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost_cny: float | None = None
    gateway_version: str | None = None
    brand_mentioned: bool | None = None
    brand_identified: bool | None = None
    brand_match_kind: str | None = None
    brand_match_term: str | None = None
    brand_match_offset: int | None = None
    brand_match_evidence: str | None = None
    brand_list_rank: int | None = None
    matcher_version: str | None = None
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


class MonitoringDiagnosticData(BaseModel):
    """内部排障列表项：失败样本、失败码、重试次数、耗时与 trace。"""

    sample_id: str
    serial_no: int
    task_id: str
    trace_id: str | None = None
    sample_status: str
    task_status: str
    attempt_no: int
    retry_count: int
    sampled_at: datetime | None = None
    finished_at: datetime | None = None
    failure_code: str | None = None
    failure_note: str | None = None
    latency_ms: int | None = None
    total_tokens: int | None = None
    estimated_cost_cny: float | None = None
    gateway_version: str | None = None
    engine_code: str | None = None
    engine_name: str | None = None
    question_code: str | None = None
    question_title: str | None = None


class SampleReviewData(BaseModel):
    """样本人工复核结果（B5 POST）。"""

    sample_id: str
    status: str
    review_result: str


class SampleReviewRecordData(BaseModel):
    """终态样本事后复核记录：不改判，只留痕。"""

    sample_id: str
    status: str
    review_result: str | None = None
    reviewed_by: str
    reviewed_at: datetime
    review_note: str


class ManualSampleCreated(BaseModel):
    """手测样本录入结果：保留 attempt 序号与自动判定结果。"""

    sample_id: str
    serial_no: int
    task_id: str
    task_status: str
    attempt_no: int
    status: str
    answer_kind: str
    sampling_mode: str | None = None
    conversation_id: str
    conversation_mode: str
    brand_mentioned: bool
    brand_identified: bool
    citation_count: int


class EvidenceUploaded(BaseModel):
    """证据文件上传结果；下载仍走 evidence/{id}/download。"""

    evidence_id: str
    sample_id: str
    file_type: str
    content_type: str | None = None
    byte_size: int
    checksum: str


class ContentStatusChanged(BaseModel):
    version_id: str
    status: str
    item_status: str


class ContentVersionLinksData(BaseModel):
    version_id: str
    question_ids: list[str]
    citation_ids: list[str]
    fact_ids: list[str] = []
    fact_links: list[ContentFactLinkData] = []


class TraceRoundItem(BaseModel):
    id: str
    seq: int
    status: str


class TraceTaskItem(BaseModel):
    id: str
    serial_no: int
    round_id: str
    status: str
    question_code: str | None = None
    question_title: str | None = None
    question_version_id: str
    version_no: int
    engine_code: str
    engine_name: str
    entry_name: str
    sampling_mode: str


class TraceSampleItem(BaseModel):
    id: str
    serial_no: int
    task_id: str
    attempt_no: int
    status: str
    brand_mentioned: bool | None = None
    failure_code: str | None = None
    failure_note: str | None = None
    latency_ms: int | None = None
    total_tokens: int | None = None
    estimated_cost_cny: float | None = None
    gateway_version: str | None = None
    sampled_at: datetime | None = None


class TraceCitationItem(BaseModel):
    id: str
    sample_id: str
    domain: str | None = None
    raw_url: str
    is_brand_related: bool
    citation_usage: str | None = None
    review_status: str | None = None


class TraceContentVersionItem(BaseModel):
    id: str
    item_id: str
    item_title: str
    version_no: int
    status: str
    content_hash: str


class TracePublishTaskItem(BaseModel):
    id: str
    serial_no: int
    version_id: str
    status: str
    publish_mode: str
    channel_name: str | None = None
    account_name: str | None = None
    trace_id: str | None = None
    created_at: datetime | None = None


class TraceCounts(BaseModel):
    rounds: int
    tasks: int
    samples: int
    citations: int
    content_versions: int
    publish_tasks: int


class TraceChainData(BaseModel):
    """一条 trace 的跨实体链路；节点为空时保持空数组，不伪造。"""

    trace_id: str
    found: bool
    rounds: list[TraceRoundItem]
    tasks: list[TraceTaskItem]
    samples: list[TraceSampleItem]
    citations: list[TraceCitationItem]
    content_versions: list[TraceContentVersionItem]
    publish_tasks: list[TracePublishTaskItem]
    counts: TraceCounts


class MonitoringReplayData(BaseModel):
    """用留存请求回放一次样本，产生新的 attempt；不重开已完成任务。"""

    sample_id: str
    task_id: str
    trace_id: str | None = None
    status: str
    brand_mentioned: bool | None = None
    citation_count: int = 0
    latency_ms: int | None = None
    total_tokens: int | None = None
    estimated_cost_cny: float | None = None
    used_stored_request: bool = False
    failure_code: str | None = None
    failure_note: str | None = None


class MonitoringResampleData(BaseModel):
    """重采样：同一轮次新建逻辑样本（新 sampling_no），等待 worker 执行。"""

    task_id: str
    round_id: str
    sampling_no: int
    status: str
    source_sample_id: str
    outbox_topic: str
    requested_at: str


class MonitoringReanalyzeData(BaseModel):
    """重分析：不请求引擎，用已留存答案重算派生字段。"""

    sample_id: str
    task_id: str
    status: str
    brand_mentioned: bool
    brand_identified: bool
    citation_count: int
    analysis_version: str | None = None
    analyzed_at: str | None = None


class CitationData(BaseModel):
    """引用列表项（B6 GET / PATCH）。"""

    citation_id: str
    sample_id: str
    raw_url: str
    normalized_url: str | None = None
    domain: str | None = None
    title: str | None = None
    position: int | None = None
    source_category: str | None = None
    page_type: str | None = None
    classification_source: str | None = None
    classification_rule_version: str | None = None
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


class SourceReviewItem(BaseModel):
    """未知被引域名审核项：站是什么、引用多少，与发布渠道完全隔离。"""

    review_id: str
    domain: str
    status: str
    source_category: str | None = None
    suggested_source_category: str | None = None
    classification_source: str | None = None
    rule_version: str | None = None
    citation_count: int
    sample_count: int
    last_sampled_at: datetime | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None


class StatSnapshotData(BaseModel):
    """一轮冻结统计快照；scope/metrics 为冻结 JSON，不再动态重算。"""

    snapshot_id: str
    round_id: str
    captured_at: datetime
    captured_by: str | None = None
    rule_version: str
    matcher_version: str
    classifier_version: str
    snapshot_hash: str
    scope: dict
    metrics: dict
    definitions: dict


class FactData(BaseModel):
    """权威事实当前记录；version_no 是内容修订号，不是历史事件序号。"""

    id: str
    fact_type: str
    fact_key: str
    fact_value: str
    source_document: str | None = None
    source_url: str | None = None
    owner: str | None = None
    approval_status: str
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    version_no: int
    superseded_by: str | None = None
    business_confirmed: bool
    business_confirmed_note: str | None = None
    created_by: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    rejection_note: str | None = None
    created_at: datetime
    updated_at: datetime


class FactVersionData(BaseModel):
    version_no: int
    action: str
    snapshot: dict
    previous_snapshot: dict | None = None
    change_note: str | None = None
    actor_id: str | None = None
    created_at: datetime


class FactClaimData(BaseModel):
    id: str
    serial_no: int
    sample_id: str
    citation_id: str | None = None
    claim_text: str
    fact_id: str | None = None
    verdict: str | None = None
    source_url: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    correction_task_id: str | None = None
    created_at: datetime


class CorrectionTaskData(BaseModel):
    id: str
    claim_id: str | None = None
    fact_id: str | None = None
    title: str
    description: str | None = None
    source_url: str | None = None
    status: str
    priority: int
    created_by: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime


class PublishAttemptCreated(BaseModel):
    attempt_id: str
    attempt_no: int
    task_status: str


class PublishAccountDeleted(BaseModel):
    id: str
    name: str | None
    deleted: bool


class PublishTaskCancelled(BaseModel):
    task_id: str
    status: str


class PublishTaskCreated(BaseModel):
    task_id: str
    serial_no: int
    status: str
    idempotency_key: str
    reused: bool
    trace_id: str | None = None


class PublishReceiptCreated(BaseModel):
    receipt_id: str
    task_id: str
    status: str


class PublishVerifyResult(BaseModel):
    task_id: str
    status: str


class PublishExecuteData(BaseModel):
    """官方 API 执行结果：成功、明确失败、结果未知都按统一结构返回。"""

    task_id: str
    status: str
    attempt_id: str
    attempt_no: int
    media_id: str | None = None
    publish_id: str | None = None
    article_url: str | None = None
    receipt_id: str | None = None
    error_code: str | None = None
    error_note: str | None = None
    status_note: str | None = None


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
    brand_identified_answers: int
    failed_samples: int
    competitor_mentions: int
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
    identified_rate: str
    citation_share: str
    sov: str
    sentiment: str
    brand_position: str
    prompt_coverage: str
    failure_rate: str
    freshness_hours: str


class StatsExcludedData(BaseModel):
    failed: int
    manual_review: int
    no_answer_surface: int = 0
    pending_or_running: int


class StatsOverviewData(BaseModel):
    valid_answers: int
    brand_mentioned_answers: int
    brand_identified_answers: int
    citation_answers: int
    brand_mention_rate: float | None = None
    brand_identified_rate: float | None = None
    citation_rate: float | None = None
    channel_count: int
    page_count: int
    excluded: StatsExcludedData
    failure_breakdown: dict[str, int] = Field(default_factory=dict)


class StatsAnswerKindOverviewData(StatsOverviewData):
    answer_kind: str


class MonthlyTaskStatsData(BaseModel):
    total: int
    done: int
    failed: int
    running: int
    pending: int
    completion_rate: float | None = None


class MonthlyAnswerStatsData(BaseModel):
    valid_answers: int
    brand_mentioned_answers: int
    citation_answers: int
    brand_mention_rate: float | None = None
    citation_rate: float | None = None
    total_samples: int
    failure_rate: float | None = None
    fresh_24h_rate: float | None = None
    prompt_coverage: float | None = None


class MonthlyReportData(BaseModel):
    """月度报告：样本完成、引用表现、线索与发布结案。

    `leads` 只有当前账号同时具备 lead.read 时才返回；只有 stats.read 的账号看得到
    样本与引用部分，不会因跨能力把月报接口整体 403。
    """

    month: str
    period_start: datetime
    period_end: datetime
    tasks: MonthlyTaskStatsData
    answers: MonthlyAnswerStatsData
    leads: LeadFunnelData | None = None
    published_receipts: int


class MonthlyReportSnapshotSummaryData(BaseModel):
    """月报历史列表的摘要；完整报告在详情接口返回。"""

    snapshot_id: str
    month: str
    period_start: datetime
    period_end: datetime
    captured_at: datetime
    captured_by: str | None = None
    captured_by_name: str | None = None
    rule_version: str
    snapshot_hash: str
    tasks_total: int
    valid_answers: int
    brand_mention_rate: float | None = None
    citation_rate: float | None = None
    published_receipts: int


class MonthlyReportSnapshotData(MonthlyReportSnapshotSummaryData):
    """冻结月报详情：report 与 definitions 均为落库时的原文。"""

    definitions: dict
    report: MonthlyReportData


class StartupMaterialItemData(BaseModel):
    """启动材料一项：已具备/部分/缺失，均给出可核对数量与说明。"""

    key: str
    label: str
    status: str
    count: int
    detail: str


class StartupMaterialsData(BaseModel):
    """启动材料盘点：缺失项一律进待补清单，不用空值冒充已具备。"""

    ready: bool
    missing: list[str]
    items: list[StartupMaterialItemData]
    generated_at: datetime


class StatsSourceData(BaseModel):
    """信源分布一行：域名 + 引用条数 + 是否命中发布回执。"""

    domain: str
    citations: int
    samples: int
    brand_related: int
    channel_citations: int
    last_sampled_at: datetime | None = None


class StatsPublishVisibilityData(BaseModel):
    """发布可见性一行：一条回执最近一次的收录检测结果。

    `error_code` 非空表示没查成（配额/鉴权/网络），此时 `matched` 恒为 false，
    不能读成"没被收录"。
    """

    receipt_id: str
    published_url: str
    checked_at: datetime | None = None
    matched: bool
    position: int | None = None
    matched_url: str | None = None
    query: str
    site: str | None = None
    result_count: int
    error_code: str | None = None


class StatsPublishVisibilityCheckData(BaseModel):
    """一次批量检测的汇总：命中 / 未收录 / 查询失败分开计数。"""

    checked: int
    matched: int
    unmatched: int
    failed: int


class StatsEngineData(BaseModel):
    engine_id: str
    engine_code: str
    engine_name: str
    valid_answers: int
    brand_mentioned_answers: int
    brand_identified_answers: int
    citation_answers: int
    brand_mention_rate: float | None = None
    brand_identified_rate: float | None = None
    citation_rate: float | None = None


class EngineHealthData(BaseModel):
    """入口级真实可用性 + 成本/延迟台账，供看板直接渲染矩阵。"""

    engine_id: str
    engine_code: str
    engine_name: str
    entry_id: str
    entry_name: str
    protocol: str
    model_name: str | None = None
    is_active: bool
    entry_url_configured: bool
    credential_configured: bool
    price_configured: bool
    task_count: int
    sample_count: int
    valid_answers: int
    failed_count: int
    failure_rate: float | None = None
    avg_latency_ms: float | None = None
    total_tokens: int
    estimated_cost_cny: float | None = None
    last_sampled_at: datetime | None = None
    availability: str
    access_note: str | None = None


class StatsQuestionData(BaseModel):
    question_id: str
    question_code: str
    question_title: str
    question_type: str
    valid_answers: int
    brand_mentioned_answers: int
    brand_identified_answers: int
    citation_answers: int
    brand_mention_rate: float | None = None
    brand_identified_rate: float | None = None
    citation_rate: float | None = None


class StatsTrendPoint(BaseModel):
    week_start: datetime
    date: datetime | None = None
    valid_answers: int
    brand_mention_rate: float | None = None


class EngineTaskShare(BaseModel):
    engine_id: str
    engine_name: str
    task_count: int
    share: float


class GeoSentimentData(BaseModel):
    positive: int
    neutral: int
    negative: int
    not_mentioned: int
    positive_rate: float | None = None
    average_score: float | None = None
    kpi_eligible: bool = False
    basis: str | None = None


class GeoBrandPositionData(BaseModel):
    sample_count: int
    average_rank: float | None = None
    top1_rate: float | None = None


class GeoOverviewData(BaseModel):
    """内部验收口径：无有效回答时比率为 null，并带 statement 说明技术基线边界。"""

    valid_answers: int
    mention_rate: float | None = None
    citation_share: float | None = None
    sov: float | None = None
    sentiment: GeoSentimentData
    brand_position: GeoBrandPositionData
    prompt_coverage: float | None = None
    freshness_hours: float | None = None
    fresh_24h_rate: float | None = None
    failure_rate: float | None = None
    statement: str
    counts: GeoOverviewCounts
    by_competitor: list[GeoCompetitorData]
    definitions: GeoDefinitionsData


class DataProvenanceProjectData(BaseModel):
    id: str
    code: str
    name: str
    status: str
    classification: str
    markers: list[str]


class DataProvenanceUserData(BaseModel):
    id: str
    username: str
    display_name: str
    classification: str


class DataProvenanceImportBatchData(BaseModel):
    id: str
    project_code: str
    source_system: str
    mapping_version: str
    status: str
    source_rows: int | None = None
    delta: dict[str, int]
    retained: bool
    started_at: datetime | None = None
    finished_at: datetime | None = None
    rollback_note: str | None = None


class DataProvenanceSummaryData(BaseModel):
    projects_total: int
    projects_by_classification: dict[str, int]
    prototype_projects: int
    seed_accounts: int
    probe_accounts: int
    demo_accounts: int
    legacy_batches_total: int
    legacy_batches_retained: int
    retained_legacy_rows: dict[str, int]


class DataProvenanceData(BaseModel):
    """P16 数据来源清点：原型/模拟项目、演示账号、历史本地导入批次与残留行数。"""

    generated_at: datetime
    summary: DataProvenanceSummaryData
    projects: list[DataProvenanceProjectData]
    users: list[DataProvenanceUserData]
    legacy_imports: list[DataProvenanceImportBatchData]


def ok(payload: Any) -> dict[str, Any]:
    return {"data": payload}


def ok_page(payload: Any, *, page: int, page_size: int, total: int) -> dict[str, Any]:
    return {"data": payload, "meta": {"page": page, "page_size": page_size, "total": total}}
