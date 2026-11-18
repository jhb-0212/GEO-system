"""全部业务枚举集中定义：数据库侧统一存字符串 + CHECK 约束，不用 PG 原生 enum，便于后续扩值。"""

from enum import StrEnum


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class RoleCode(StrEnum):
    """六个角色：系统级与项目级管理员分开，禁止混用。

    sys_admin     系统管理员：建项目、维护引擎目录、系统级配置；不默认读写项目业务数据
    project_admin 项目管理员：管理本项目成员，只能授予 editor/reviewer/viewer/lead_ops
    editor        运营/编辑：题库、监测、内容、发布、渠道
    reviewer      审核：内容审批、证据复核，不改正文、不发布
    viewer        只读：所有写操作拒绝，导出需 export.data 能力并留痕
    lead_ops      招生/客服：只能读写本项目线索
    """

    SYS_ADMIN = "sys_admin"
    PROJECT_ADMIN = "project_admin"
    EDITOR = "editor"
    REVIEWER = "reviewer"
    VIEWER = "viewer"
    LEAD_OPS = "lead_ops"


class PermissionScope(StrEnum):
    """能力作用域：system 由系统管理员持有，project 由项目成员角色持有。"""

    SYSTEM = "system"
    PROJECT = "project"


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


class EngineProtocol(StrEnum):
    """入口调用协议：运营自接入只开放已实现的协议，其他走 custom 后续开发。"""

    OPENAI_COMPATIBLE = "openai_compatible"
    YUANBAO_SEARCH = "yuanbao_search"
    DOUBAO_SEARCH = "doubao_search"
    WENXIN_SEARCH = "wenxin_search"
    DEEPSEEK_WEB_SEARCH = "deepseek_web_search"
    CUSTOM = "custom"


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
    # 外部请求已发出但结果未落库（Worker 崩溃/租约过期）：不能盲目重发，需人工核实
    UNCERTAIN = "uncertain"


class AttemptStatus(StrEnum):
    """一次执行尝试的状态：与任务状态分开，保证每次领取都有独立记录。"""

    CLAIMED = "claimed"          # 已领取，尚未发出外部请求
    DISPATCHING = "dispatching"  # 正在调用外部平台
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"  # 本地限流拒绝，未调用外部平台
    LEASE_EXPIRED = "lease_expired"  # 领取后未发出请求即失联，可安全重排
    UNCERTAIN = "uncertain"      # 请求已发出、结果未知，禁止自动重发


class SampleStatus(StrEnum):
    """采样结果状态机：待执行 → 执行中 → 有效命中/有效未命中/无答案面/执行失败/待人工复核。

    `NO_ANSWER_SURFACE` 表示入口可访问、请求成功，但该 AI 产品没有呈现可分析的
    答案（空正文且无检索结果）。它既不是"有效未命中"，也不是技术失败，
    不进入提及率/引用率的有效分母，也不计入技术失败率。
    """

    PENDING = "pending"
    RUNNING = "running"
    HIT = "hit"
    MISS = "miss"
    NO_ANSWER_SURFACE = "no_answer_surface"
    FAILED = "failed"
    MANUAL_REVIEW = "manual_review"


class AnswerKind(StrEnum):
    """样本答案口径：生成回答 vs 检索结果。

    - `answer`：AI 生成回答（含网页端/官方 Responses 类），提及率按“回答内容”统计；
    - `search_result`：只返回检索结果列表（元宝 SearchPro / DeepSeek tools-search / 千帆 AI 搜索），
      提及率按“检索可见性”统计，两类**不得合并**算同一个提及率。
    """

    ANSWER = "answer"
    SEARCH_RESULT = "search_result"


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


class CitationUsage(StrEnum):
    """引用角色：used=影响了回答但未明确引用；cited=回答中明确给出 URL。"""

    USED = "used"
    CITED = "cited"


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


class BudgetCategory(StrEnum):
    """四类预算：开发工时、内容制作、媒体投放、监测服务。"""

    DEVELOPMENT_HOURS = "development_hours"
    CONTENT_PRODUCTION = "content_production"
    MEDIA_PLACEMENT = "media_placement"
    MONITORING_SERVICE = "monitoring_service"


class BudgetApprovalStatus(StrEnum):
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


class VerifyOutcome(StrEnum):
    PUBLISHED = "published"          # 核实已发出：补回执结案
    NOT_PUBLISHED = "not_published"  # 核实未发出：回 pending 重试，不新建任务


class EnrollmentStatus(StrEnum):
    UNKNOWN = "unknown"
    CONTACTED = "contacted"
    ENROLLED = "enrolled"
    LOST = "lost"


class FaqStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    UNPUBLISHED = "unpublished"


class MaterialCategory(StrEnum):
    IMAGE = "image"
    DOCUMENT = "document"
    CASE = "case"


class MetricStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    FAILED = "failed"


class ImportBatchStatus(StrEnum):
    """历史数据导入批次状态：批次是旧数据标识、数量核对与回滚追溯的唯一依据。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
