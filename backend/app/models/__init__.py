"""业务数据模型包。

所有项目业务表必须带 project_id 归属标识（系统参考数据 ai_engines / ai_engine_entries 除外）。
新增模型必须在这里 import，否则 Alembic 自动生成时看不到表。

## 快照三分法（读旧表名容易混，先看这里）

系统里有四张带 snapshot 的表，其实是**三层**职责，不是四个同类东西：

| 层 | 表 | 回答什么问题 | 可变性 |
|---|---|---|---|
| 证据（EvidenceSnapshot） | `AnswerSnapshot` | 「当时 AI 到底说了什么」——原始回答原文 | 追加一次，永不更新 |
| 口径（MethodSnapshot） | `MeasurementSnapshot` | 「这一轮按什么规则测的」——别名、问题集、引擎口径 | 一轮冻结一次 |
| 指标（MetricSnapshot） | `StatSnapshot` | 「那一刻算出来的数是多少」——引用率/覆盖率等冻结值 | 一期冻结一次 |
| 指标（月度视图） | `MonthlyReportSnapshot` | 月报引用的指标快照集合 | 一月冻结一次 |

用法速查：要复现三个月前的 62%，先读 `StatSnapshot` 拿数，
再顺 `MeasurementSnapshot` 看口径，需要原文证据时读 `AnswerSnapshot`。
不要用口径快照解释数值，也不要用数值快照反推原文。
"""

from app.db.base import Base
from app.models.brand import BrandProfile
from app.models.channel import Channel, ChannelAlias, ChannelApproval
from app.models.company import CompanyProfile
from app.models.contacts import ProjectContact
from app.models.distribution import (
    DistributionBatch,
    DistributionBatchItem,
    DistributionPush,
)
from app.models.content import (
    BudgetApproval,
    ContentItem,
    ContentPlan,
    ContentReview,
    ContentVersion,
    ContentVersionCitation,
    ContentVersionFact,
    ContentVersionKeyword,
    ContentVersionQuestion,
    MediaQuote,
    PublicPage,
)
from app.models.engine import AiEngine, AiEngineEntry
from app.models.encyclopedia import EncyclopediaEntry
from app.models.facts import AnswerFactClaim, CorrectionTask, Fact, FactVersion
from app.models.generation import (
    GenerationBatch,
    GenerationGateResult,
    GenerationItem,
)
from app.models.health_check import HealthCheckItem, HealthCheckRun
from app.models.knowledge import Certification, Faq, Material
from app.models.knowledge_base import KnowledgeCandidateFact, KnowledgeChunk, KnowledgeDocument
from app.models.lead import Lead, LeadMessage
from app.models.media_matrix import MediaMatrixConfig
from app.models.microsite import SiteModule, SiteSite
from app.models.monitoring import (
    CitationSourceReview,
    Competitor,
    EvidenceFile,
    MonitoringBrandMention,
    MonitoringExecutionAttempt,
    MonitoringCitation,
    MonitoringCompetitorMention,
    MonitoringRound,
    MonitoringSample,
    MonitoringSourceProfile,
    MonitoringTask,
    MonitoringRetestPlan,
)
from app.models.oauth import OAuthAuthorizationState, OAuthConnection
from app.models.alerts import AlertEvent, AlertRule
from app.models.api_key import ApiKey
from app.models.lead_attribution import LeadAttribution
from app.models.media_provider import MediaOrder, MediaProvider
from app.models.opportunity import Opportunity, OpportunitySuggestion
from app.models.sentiment import SentimentLabel
from app.models.source_domain import SourceDomainEvidence
from app.models.engine_target import EngineTarget
from app.models.project_policy import ProjectPolicy
from app.models.industry import (
    IndustryPreset,
    Organization,
    OrganizationMember,
    OrganizationUsageSnapshot,
    ProjectStrategy,
)
from app.models.snapshot import AnswerSnapshot
from app.models.selling_point import SellingPoint
from app.models.brand_search import BrandSearchSnapshot
from app.models.templates import ContentTemplate
from app.models.derivations import ContentDerivation
from app.models.page_approval import PageApproval
from app.models.publishing import (
    PublishAccount,
    PublishAttempt,
    PublishReceipt,
    PublishTask,
    PublishVisibilityCheck,
)
from app.models.site import CrawlerEvent, TrafficEvent
from app.models.stats import MonthlyReportSnapshot, ReportShare, StatSnapshot
from app.models.usage import UsageEvent
from app.models.question import (
    Keyword,
    Question,
    QuestionCandidate,
    QuestionKeyword,
    QuestionVersion,
    QuestionVersionKeyword,
)
from app.models.system import (
    AuditLog,
    ImportBatch,
    MetricDefinition,
    OutboxEvent,
    Permission,
    Project,
    ProjectMember,
    Role,
    RolePermission,
    User,
)

__all__ = [
    "AiEngine",
    "AiEngineEntry",
    "EngineTarget",
    "ProjectPolicy",
    "IndustryPreset",
    "Organization",
    "OrganizationMember",
    "ProjectStrategy",
    "AnswerFactClaim",
    "AnswerSnapshot",
    "AuditLog",
    "Base",
    "BrandProfile",
    "BrandSearchSnapshot",
    "BudgetApproval",
    "Channel",
    "ChannelAlias",
    "ChannelApproval",
    "CitationSourceReview",
    "CompanyProfile",
    "Competitor",
    "ContentItem",
    "ContentPlan",
    "ContentReview",
    "ContentVersion",
    "ContentVersionCitation",
    "ContentTemplate",
    "ContentDerivation",
    "ContentVersionFact",
    "ContentVersionKeyword",
    "ContentVersionQuestion",
    "CorrectionTask",
    "CrawlerEvent",
    "EvidenceFile",
    "Fact",
    "FactVersion",
    "DistributionBatch",
    "DistributionBatchItem",
    "DistributionPush",
    "DistributionBatchItem",
    "EncyclopediaEntry",
    "Faq",
    "GenerationBatch",
    "GenerationGateResult",
    "GenerationItem",
    "HealthCheckItem",
    "HealthCheckRun",
    "ImportBatch",
    "Keyword",
    "Lead",
    "LeadMessage",
    "MediaMatrixConfig",
    "SiteSite",
    "SiteModule",
    "Certification",
    "Material",
    "KnowledgeCandidateFact",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "MediaQuote",
    "MetricDefinition",
    "MonthlyReportSnapshot",
    "ReportShare",
    "MonitoringBrandMention",
    "MonitoringCitation",
    "MonitoringCompetitorMention",
    "MonitoringExecutionAttempt",
    "MonitoringRound",
    "MonitoringRetestPlan",
    "MonitoringSample",
    "MonitoringSourceProfile",
    "MonitoringTask",
    "OAuthAuthorizationState",
    "OAuthConnection",
    "AlertEvent",
    "AlertRule",
    "ApiKey",
    "LeadAttribution",
    "MediaOrder",
    "MediaProvider",
    "Opportunity",
    "OpportunitySuggestion",
    "OutboxEvent",
    "PageApproval",
    "Permission",
    "Project",
    "ProjectContact",
    "ProjectMember",
    "PublicPage",
    "PublishAccount",
    "PublishAttempt",
    "PublishReceipt",
    "PublishTask",
    "PublishVisibilityCheck",
    "Question",
    "QuestionCandidate",
    "QuestionKeyword",
    "QuestionVersion",
    "QuestionVersionKeyword",
    "Role",
    "RolePermission",
    "SentimentLabel",
    "SellingPoint",
    "StatSnapshot",
    "TrafficEvent",
    "UsageEvent",
    "User",
]
