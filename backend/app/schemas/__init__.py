"""接口请求模型：集中在 app/schemas，路由层只做编排。"""

from app.schemas.brand import BrandProfileUpsert
from app.schemas.budget import (
    BudgetApprovalCreate,
    BudgetApprovalReview,
    BudgetReceiptLinkCreate,
)
from app.schemas.channels import ChannelCreate, ChannelDeleted, ChannelReviewRequest, ChannelUpdate
from app.schemas.citations import (
    CitationPageTypeRequest,
    CitationReviewRequest,
    CitationSourceBulkClassifyRequest,
)
from app.schemas.company import (
    CompanyProfileUpsert,
    CompanyProfileViewInput,
    CompanyProfileViewsUpsert,
    CompanyProductInput,
)
from app.schemas.competitors import CompetitorCreate, CompetitorDeleted, CompetitorUpdate
from app.schemas.content import (
    ContentBodyUpdate,
    ContentItemCreate,
    ContentReviewRequest,
    ContentStatusUpdate,
    ContentVersionCreate,
    ContentVersionLinksUpdate,
    SellingPointCreate,
    SellingPointUpdate,
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
from app.schemas.knowledge import FaqCreate, FaqReviewRequest, FaqUpdate, MaterialUpdate
from app.schemas.leads import LeadAutoreplyIn, LeadCreate, LeadMessageCreate, LeadUpdate, PublicLeadCreate
from app.schemas.members import MemberGrant, MemberRoleChange
from app.schemas.metrics import MetricDefinitionCreate, MetricDefinitionUpdate
from app.schemas.page_approvals import (
    PageApprovalCreate,
    PageApprovalReview,
    PageApprovalRevoke,
)
from app.schemas.monitoring import (    BatchGenerateRequest,
    ManualFailureCreate,
    ManualSampleCreate,
    RetestPlanCreate,
    RetestPlanUpdate,
    RoundCreate,
    SampleReviewRecordRequest,
    SampleReviewRequest,
)
from app.schemas.alerts import AlertEvaluateRequest, AlertEventAck, AlertRuleUpdate
from app.schemas.api_keys import ApiKeyCreate, McpRequest
from app.schemas.media_adapters import (
    MediaManualStatus,
    MediaOrderCreate,
    MediaProviderCreate,
    MediaProviderUpdate,
    MediaQuoteRequest,
)
from app.schemas.opportunities import (
    OpportunityCreate,
    OpportunitySuggestionAccept,
    OpportunitySuggestionDismiss,
    OpportunitySuggestionGenerate,
    OpportunityUpdate,
)
from app.schemas.oauth import OAuthAuthorizeRequest
from app.schemas.site_diagnostics import (
    CrawlerEventImport,
    CrawlerEventCreate,
    TrafficEventImport,
    TrafficEventCreate,
)
from app.schemas.pages import PageCreate, PageUpdate
from app.schemas.plans import PlanCreate, PlanUpdate
from app.schemas.projects import EngineCreate, ProjectConfirm, ProjectCreate, ProjectTimezoneUpdate
from app.schemas.questions import QuestionCreate, QuestionUpdate, QuestionVersionCreate
from app.schemas.question_candidates import (
    QuestionCandidateImport,
    QuestionCandidateMine,
)
from app.schemas.knowledge_base import KnowledgeCandidateAccept, KnowledgeCandidateReject
from app.schemas.report_shares import ReportShareCreate, ReportSharePassword
from app.schemas.quotes import QuoteCreate, QuoteReview, QuoteUpdate
from app.schemas.publishing import (
    PublishAccountCreate,
    PublishAccountUpdate,
    PublishAttemptCreate,
    PublishHandoffCreate,
    PublishReceiptCreate,
    PublishTaskCreate,
    PublishVerifyRequest,
    PublishWeChatExecuteRequest,
)

__all__ = [
    "BrandProfileUpsert",
    "BudgetApprovalCreate",
    "BudgetApprovalReview",
    "BatchGenerateRequest",
    "ChannelCreate",
    "ChannelDeleted",
    "ChannelReviewRequest",
    "ChannelUpdate",
    "CitationPageTypeRequest",
    "CitationReviewRequest",
    "CompetitorCreate",
    "CompetitorDeleted",
    "CompetitorUpdate",
    "ContentBodyUpdate",
    "ContentItemCreate",
    "ContentReviewRequest",
    "ContentStatusUpdate",
    "ContentVersionCreate",
    "ContentVersionLinksUpdate",
    "SellingPointCreate",
    "SellingPointUpdate",
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
    "FaqReviewRequest",
    "FaqUpdate",
    "KeywordCreate",
    "KeywordUpdate",
    "LeadCreate",
    "LeadMessageCreate",
    "LeadUpdate",
    "PublicLeadCreate",
    "MaterialUpdate",
    "ManualFailureCreate",
    "ManualSampleCreate",
    "RetestPlanCreate",
    "RetestPlanUpdate",
    "MemberGrant",
    "MemberRoleChange",
    "MetricDefinitionCreate",
    "MetricDefinitionUpdate",
    "AlertEvaluateRequest",
    "AlertEventAck",
    "AlertRuleUpdate",
    "ApiKeyCreate",
    "McpRequest",
    "MediaManualStatus",
    "MediaOrderCreate",
    "MediaProviderCreate",
    "MediaProviderUpdate",
    "MediaQuoteRequest",
    "OpportunityCreate",
    "OpportunitySuggestionAccept",
    "OpportunitySuggestionDismiss",
    "OpportunitySuggestionGenerate",
    "OpportunityUpdate",
    "OAuthAuthorizeRequest",
    "PageApprovalCreate",
    "PageApprovalReview",
    "PageApprovalRevoke",
    "PageCreate",
    "PageUpdate",
    "PlanCreate",
    "PlanUpdate",
    "ProjectCreate",
    "ProjectConfirm",
    "PublishAccountCreate",
    "PublishAccountUpdate",
    "PublishAttemptCreate",
    "PublishHandoffCreate",
    "PublishReceiptCreate",
    "PublishTaskCreate",
    "PublishVerifyRequest",
    "PublishWeChatExecuteRequest",
    "QuestionCreate",
    "QuestionCandidateImport",
    "QuestionCandidateMine",
    "KnowledgeCandidateAccept",
    "KnowledgeCandidateReject",
    "QuestionUpdate",
    "QuestionVersionCreate",
    "QuoteCreate",
    "QuoteReview",
    "QuoteUpdate",
    "ReportShareCreate",
    "ReportSharePassword",
    "RoundCreate",
    "SampleReviewRecordRequest",
    "SampleReviewRequest",
    "TrafficEventCreate",
    "TrafficEventImport",
]
