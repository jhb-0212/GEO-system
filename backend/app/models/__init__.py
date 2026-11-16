"""业务数据模型包。

所有项目业务表必须带 project_id 归属标识（系统参考数据 ai_engines / ai_engine_entries 除外）。
新增模型必须在这里 import，否则 Alembic 自动生成时看不到表。
"""

from app.db.base import Base
from app.models.channel import Channel, ChannelAlias
from app.models.content import (
    ContentItem,
    ContentPlan,
    ContentReview,
    ContentVersion,
    ContentVersionCitation,
    ContentVersionKeyword,
    ContentVersionQuestion,
    MediaQuote,
    PublicPage,
)
from app.models.engine import AiEngine, AiEngineEntry
from app.models.lead import Lead
from app.models.monitoring import (
    Competitor,
    EvidenceFile,
    MonitoringCitation,
    MonitoringCompetitorMention,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
)
from app.models.publishing import (
    PublishAccount,
    PublishAttempt,
    PublishReceipt,
    PublishTask,
)
from app.models.question import Keyword, Question, QuestionKeyword, QuestionVersion
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
    "AuditLog",
    "Base",
    "Channel",
    "ChannelAlias",
    "Competitor",
    "ContentItem",
    "ContentPlan",
    "ContentReview",
    "ContentVersion",
    "ContentVersionCitation",
    "ContentVersionKeyword",
    "ContentVersionQuestion",
    "EvidenceFile",
    "ImportBatch",
    "Keyword",
    "Lead",
    "MediaQuote",
    "MetricDefinition",
    "MonitoringCitation",
    "MonitoringCompetitorMention",
    "MonitoringRound",
    "MonitoringSample",
    "MonitoringTask",
    "OutboxEvent",
    "Permission",
    "Project",
    "ProjectMember",
    "PublicPage",
    "PublishAccount",
    "PublishAttempt",
    "PublishReceipt",
    "PublishTask",
    "Question",
    "QuestionKeyword",
    "QuestionVersion",
    "Role",
    "RolePermission",
    "User",
]
