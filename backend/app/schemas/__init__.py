"""接口请求模型：集中在 app/schemas，路由层只做编排。"""

from app.schemas.brand import BrandProfileUpsert
from app.schemas.budget import BudgetApprovalCreate, BudgetApprovalReview
from app.schemas.channels import ChannelCreate, ChannelReviewRequest, ChannelUpdate
from app.schemas.citations import CitationPageTypeRequest, CitationReviewRequest
from app.schemas.competitors import CompetitorCreate, CompetitorUpdate
from app.schemas.content import (
    ContentBodyUpdate,
    ContentItemCreate,
    ContentReviewRequest,
    ContentStatusUpdate,
    ContentVersionCreate,
    ContentVersionLinksUpdate,
)
from app.schemas.engines import EngineEntryCreate, EngineEntryUpdate, EngineEntryVerify
from app.schemas.facts import (
    CorrectionTaskUpdate,
    FactClaimCreate,
    FactClaimReviewRequest,
    FactCreate,
    FactReviewRequest,
    FactUpdate,
)
from app.schemas.keywords import KeywordCreate, KeywordUpdate
from app.schemas.knowledge import FaqCreate, FaqUpdate, MaterialUpdate
from app.schemas.leads import LeadCreate, LeadUpdate
from app.schemas.members import MemberGrant, MemberRoleChange
from app.schemas.metrics import MetricDefinitionCreate, MetricDefinitionUpdate
from app.schemas.monitoring import ManualSampleCreate, RoundCreate, SampleReviewRequest
from app.schemas.opportunities import OpportunityCreate, OpportunityUpdate
from app.schemas.site_diagnostics import (
    CrawlerEventImport,
    CrawlerEventCreate,
    TrafficEventImport,
    TrafficEventCreate,
)
from app.schemas.pages import PageCreate, PageUpdate
from app.schemas.plans import PlanCreate, PlanUpdate
from app.schemas.projects import EngineCreate, ProjectConfirm, ProjectCreate
from app.schemas.questions import QuestionCreate, QuestionUpdate, QuestionVersionCreate
from app.schemas.quotes import QuoteCreate, QuoteReview, QuoteUpdate
from app.schemas.publishing import (
    PublishAccountCreate,
    PublishAttemptCreate,
    PublishReceiptCreate,
    PublishTaskCreate,
    PublishVerifyRequest,
)

__all__ = [
    "BrandProfileUpsert",
    "BudgetApprovalCreate",
    "BudgetApprovalReview",
    "ChannelCreate",
    "ChannelReviewRequest",
    "ChannelUpdate",
    "CitationPageTypeRequest",
    "CitationReviewRequest",
    "CompetitorCreate",
    "CompetitorUpdate",
    "ContentBodyUpdate",
    "ContentItemCreate",
    "ContentReviewRequest",
    "ContentStatusUpdate",
    "ContentVersionCreate",
    "ContentVersionLinksUpdate",
    "CorrectionTaskUpdate",
    "CrawlerEventCreate",
    "CrawlerEventImport",
    "EngineCreate",
    "EngineEntryCreate",
    "EngineEntryUpdate",
    "EngineEntryVerify",
    "FactClaimCreate",
    "FactClaimReviewRequest",
    "FactCreate",
    "FactReviewRequest",
    "FactUpdate",
    "FaqCreate",
    "FaqUpdate",
    "KeywordCreate",
    "KeywordUpdate",
    "LeadCreate",
    "LeadUpdate",
    "MaterialUpdate",
    "ManualSampleCreate",
    "MemberGrant",
    "MemberRoleChange",
    "MetricDefinitionCreate",
    "MetricDefinitionUpdate",
    "OpportunityCreate",
    "OpportunityUpdate",
    "PageCreate",
    "PageUpdate",
    "PlanCreate",
    "PlanUpdate",
    "ProjectCreate",
    "ProjectConfirm",
    "PublishAccountCreate",
    "PublishAttemptCreate",
    "PublishReceiptCreate",
    "PublishTaskCreate",
    "PublishVerifyRequest",
    "QuestionCreate",
    "QuestionUpdate",
    "QuestionVersionCreate",
    "QuoteCreate",
    "QuoteReview",
    "QuoteUpdate",
    "RoundCreate",
    "SampleReviewRequest",
    "TrafficEventCreate",
    "TrafficEventImport",
]
