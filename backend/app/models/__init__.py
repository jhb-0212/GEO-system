"""业务数据模型包。

所有项目业务表必须带 project_id 归属标识（系统参考数据 ai_engines / ai_engine_entries 除外）。
新增模型必须在这里 import，否则 Alembic 自动生成时看不到表。
"""

from app.db.base import Base
from app.models.brand import BrandProfile
from app.models.channel import Channel, ChannelAlias, ChannelApproval
from app.models.company import CompanyProfile
from app.models.contacts import ProjectContact
from app.models.distribution import DistributionBatch, DistributionBatchItem
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
from app.models.generation import GenerationBatch, GenerationItem
from app.models.health_check import HealthCheckItem, HealthCheckRun
from app.models.knowledge import Certification, Faq, Material
from app.models.lead import Lead, LeadMessage
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
from app.models.opportunity import Opportunity
from app.models.sentiment import SentimentLabel
from app.models.source_domain import SourceDomainEvidence
from app.models.engine_target import EngineTarget
from app.models.snapshot import AnswerSnapshot
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
from app.models.stats import MonthlyReportSnapshot, StatSnapshot
from app.models.question import (
    Keyword,
    Question,
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
    "AnswerFactClaim",
    "AnswerSnapshot",
    "AuditLog",
    "Base",
    "BrandProfile",
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
    "EncyclopediaEntry",
    "Faq",
    "GenerationBatch",
    "GenerationItem",
    "HealthCheckItem",
    "HealthCheckRun",
    "ImportBatch",
    "Keyword",
    "Lead",
    "LeadMessage",
    "SiteSite",
    "SiteModule",
    "Certification",
    "Material",
    "MediaQuote",
    "MetricDefinition",
    "MonthlyReportSnapshot",
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
    "Opportunity",
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
    "QuestionKeyword",
    "QuestionVersion",
    "QuestionVersionKeyword",
    "Role",
    "RolePermission",
    "SentimentLabel",
    "StatSnapshot",
    "TrafficEvent",
    "User",
]
