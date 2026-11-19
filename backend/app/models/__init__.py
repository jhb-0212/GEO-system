"""业务数据模型包。

所有项目业务表必须带 project_id 归属标识（系统参考数据 ai_engines / ai_engine_entries 除外）。
新增模型必须在这里 import，否则 Alembic 自动生成时看不到表。
"""

from app.db.base import Base
from app.models.brand import BrandProfile
from app.models.channel import Channel, ChannelAlias
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
from app.models.facts import AnswerFactClaim, CorrectionTask, Fact, FactVersion
from app.models.knowledge import Faq, Material
from app.models.lead import Lead
from app.models.monitoring import (
    CitationSourceReview,
    Competitor,
    EvidenceFile,
    MonitoringExecutionAttempt,
    MonitoringBrandMention,
    MonitoringCitation,
    MonitoringCompetitorMention,
    MonitoringRound,
    MonitoringSample,
    MonitoringSourceProfile,
    MonitoringTask,
)
from app.models.opportunity import Opportunity
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
    "AnswerFactClaim",
    "AuditLog",
    "Base",
    "BrandProfile",
    "BudgetApproval",
    "Channel",
    "ChannelAlias",
    "CitationSourceReview",
    "Competitor",
    "ContentItem",
    "ContentPlan",
    "ContentReview",
    "ContentVersion",
    "ContentVersionCitation",
    "ContentVersionFact",
    "ContentVersionKeyword",
    "ContentVersionQuestion",
    "CorrectionTask",
    "CrawlerEvent",
    "EvidenceFile",
    "Fact",
    "FactVersion",
    "Faq",
    "ImportBatch",
    "Keyword",
    "Lead",
    "Material",
    "MediaQuote",
    "MetricDefinition",
    "MonitoringCitation",
    "MonitoringBrandMention",
    "MonitoringCompetitorMention",
    "MonitoringExecutionAttempt",
    "MonitoringRound",
    "MonitoringSample",
    "MonitoringSourceProfile",
    "MonitoringTask",
    "Opportunity",
    "OutboxEvent",
    "Permission",
    "Project",
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
    "MonthlyReportSnapshot",
    "StatSnapshot",
    "TrafficEvent",
    "User",
]
