"""全部业务枚举集中定义：数据库侧统一存字符串 + CHECK 约束，不用 PG 原生 enum，便于后续扩值。"""

from enum import StrEnum


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class RoleCode(StrEnum):
    ADMIN = "admin"          # 管理员
    EDITOR = "editor"        # 运营 / 编辑
    REVIEWER = "reviewer"    # 审核人员
    VIEWER = "viewer"        # 只读人员
    LEAD_OPS = "lead_ops"    # 招生 / 客服，仅线索相关


class QuestionType(StrEnum):
    BRAND = "brand"      # 品牌题，用基地全称核对品牌识别
    GENERAL = "general"  # 通用题，不带品牌名，测自然发现


class QuestionStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class EngineEntryType(StrEnum):
    WEB_USER = "web_user"      # 网页用户端
    APP_USER = "app_user"      # 客户端
    API = "api"                # 官方 API
    APP_SEARCH = "app_search"  # 应用内搜索


class RoundStatus(StrEnum):
    PLANNING = "planning"
    RUNNING = "running"
    COMPLETED = "completed"
    CLOSED = "closed"


class SamplingMode(StrEnum):
    SEARCH_ON = "search_on"
    SEARCH_OFF = "search_off"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SampleStatus(StrEnum):
    """采样结果状态机：待执行 → 执行中 → 有效命中/有效未命中/执行失败/待人工复核。"""

    PENDING = "pending"
    RUNNING = "running"
    HIT = "hit"
    MISS = "miss"
    FAILED = "failed"
    MANUAL_REVIEW = "manual_review"


class FailureCode(StrEnum):
    """失败原因单独分类，不得计入有效未命中分母。"""

    LOGIN_BLOCKED = "login_blocked"
    TIMEOUT = "timeout"
    ACCESS_BLOCKED = "access_blocked"
    CAPTCHA = "captcha"
    RATE_LIMITED = "rate_limited"
    OTHER = "other"


class ReviewResult(StrEnum):
    HIT = "hit"
    MISS = "miss"


class CitationReviewStatus(StrEnum):
    AUTO = "auto"
    MANUAL_CONFIRMED = "manual_confirmed"
    MANUAL_REJECTED = "manual_rejected"


class EvidenceFileType(StrEnum):
    SCREENSHOT = "screenshot"
    ATTACHMENT = "attachment"
    PDF = "pdf"
    OTHER = "other"


class ChannelCategory(StrEnum):
    OWN_SITE = "own_site"
    CONTENT_PLATFORM = "content_platform"
    VIDEO = "video"
    COMMUNITY = "community"
    ENCYCLOPEDIA = "encyclopedia"
    LOCAL_MEDIA = "local_media"
    INDUSTRY_MEDIA = "industry_media"
    INSTITUTION = "institution"


class ChannelStatus(StrEnum):
    CANDIDATE = "candidate"
    PUBLISHED = "published"
    OBSERVED = "observed"
    REVIEW_PENDING = "review_pending"


class ContentKind(StrEnum):
    MASTER = "master"    # 母稿
    CHANNEL = "channel"  # 渠道稿


class ContentStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    NEEDS_ATTENTION = "needs_attention"
    ARCHIVED = "archived"


class ReviewDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class PlanType(StrEnum):
    ARTICLE = "article"
    VIDEO = "video"


class ContentPlanStatus(StrEnum):
    PROPOSED = "proposed"
    SCHEDULED = "scheduled"
    IN_PRODUCTION = "in_production"
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    CANCELLED = "cancelled"


class PageType(StrEnum):
    HOME = "home"
    COURSE = "course"
    FAQ = "faq"
    CASE = "case"
    CONTACT = "contact"
    OTHER = "other"


class PagePublishStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    OFFLINE = "offline"


class QuoteStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class PublishMode(StrEnum):
    MANUAL = "manual"
    API = "api"
    AUTHORIZED = "authorized"


class PublishTaskStatus(StrEnum):
    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    UNKNOWN = "unknown"          # 回执不明，先核实不重发
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    CANCELLED = "cancelled"


class AttemptResult(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    UNKNOWN = "unknown"


class EnrollmentStatus(StrEnum):
    UNKNOWN = "unknown"
    CONTACTED = "contacted"
    ENROLLED = "enrolled"
    LOST = "lost"


class MetricStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    FAILED = "failed"
