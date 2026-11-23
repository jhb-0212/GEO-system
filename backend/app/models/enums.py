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


class DistributionBatchStatus(StrEnum):
    """投喂批次状态：预检未过=b blocked，全过=ready，人工标记=dispatched。"""

    BLOCKED = "blocked"
    READY = "ready"
    DISPATCHED = "dispatched"


class SentimentPolarity(StrEnum):
    """人工标注的原文倾向：只记录人判定的结论，系统不自动猜情绪。"""

    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class SourceCategory(StrEnum):
    """引用来源类别：站点是什么，不等于我们是否在该站发布过内容。"""

    BRAND_OWNED = "brand_owned"
    COMPETITOR_OWNED = "competitor_owned"
    SOCIAL_COMMUNITY = "social_community"
    CONTENT_PLATFORM = "content_platform"
    NEWS_MEDIA = "news_media"
    INDUSTRY_MEDIA = "industry_media"
    GOVERNMENT_INSTITUTION = "government_institution"
    EDUCATION_INSTITUTION = "education_institution"
    REFERENCE = "reference"
    ECOMMERCE = "ecommerce"
    OTHER = "other"
    UNKNOWN = "unknown"


class CitationPageType(StrEnum):
    """引用页面类型：同一站点首页、教程、榜单可以是不同页型。"""

    HOMEPAGE = "homepage"
    COURSE_OR_PRODUCT = "course_or_product"
    ARTICLE = "article"
    LISTICLE = "listicle"
    HOW_TO = "how_to"
    COMPARISON = "comparison"
    REVIEW = "review"
    FORUM_OR_QA = "forum_or_qa"
    VIDEO = "video"
    CASE_STUDY = "case_study"
    FAQ = "faq"
    ADMISSIONS = "admissions"
    RECRUITMENT = "recruitment"
    SEARCH_SURFACE = "search_surface"
    OTHER = "other"


class ClassificationSource(StrEnum):
    """分类来源：规则自动判断，或人工覆盖。"""

    RULE = "rule"
    MANUAL = "manual"


class SourceReviewStatus(StrEnum):
    """未知被引域名的独立审核状态：不自动创建发布渠道。"""

    PENDING = "pending"
    CLASSIFIED = "classified"
    IGNORED = "ignored"


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


class ChannelApprovalStatus(StrEnum):
    """渠道准入审批状态：与业务四态正交，控制渠道能否被发布/引用归属。

    - pending_review 待审核：新建渠道默认，未准入前不能建发布任务、不能挂接引用回执；
    - approved 已准入：项目管理员审批通过，可进入发布与归因链；
    - rejected 已驳回：审批未通过，可修改后重新提交。
    """

    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class PageApprovalStatus(StrEnum):
    """页面级发布审批状态；逐页审批，不随渠道审批自动通过。"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"


class PagePermission(StrEnum):
    """页面归属与发布权限。

    - official：渠道主体自己的官方页面，可作为官方发布页；
    - authorized：渠道主体授权代运营/合作页面，可发布但需保留授权依据；
    - third_party：媒体、百科、转载页，只能作为引用/观察来源，不能作为官方发布页。
    """

    OFFICIAL = "official"
    AUTHORIZED = "authorized"
    THIRD_PARTY = "third_party"


class ContentKind(StrEnum):
    MASTER = "master"    # 母稿
    CHANNEL = "channel"  # 渠道稿


class ContentStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SCHEDULED = "scheduled"
    PENDING_PUBLISH = "pending_publish"
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


class OpportunityGapType(StrEnum):
    """机会缺口类型：决定这条任务是补页面、补媒体、补参考站还是修事实。"""

    OWN_PAGE = "own_page"
    MEDIA_REPORT = "media_report"
    REFERENCE_SITE = "reference_site"
    UGC = "ugc"
    FACT_CORRECTION = "fact_correction"
    WEBSITE_FIX = "website_fix"


class OpportunityStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    DISMISSED = "dismissed"


class PageType(StrEnum):
    HOME = "home"
    COURSE = "course"
    FAQ = "faq"
    CASE = "case"
    CONTACT = "contact"
    ADMISSIONS = "admissions"
    RECRUITMENT = "recruitment"
    OTHER = "other"


class PagePublishStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    OFFLINE = "offline"


class EncyclopediaStatus(StrEnum):
    """百科词条的站内流转；发布动作指「在第三方百科平台上线」并回登外链。"""

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    REJECTED = "rejected"


class QuoteStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


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


class PublishHandoffReason(StrEnum):
    """发布转人工原因；写在 attempt.error_code，不改任务终态语义。"""

    QR_REQUIRED = "qr_required"
    CAPTCHA_REQUIRED = "captcha_required"
    SESSION_EXPIRED = "session_expired"
    LOGIN_BLOCKED = "login_blocked"
    RATE_LIMITED = "rate_limited"
    BROWSER_SESSION_REQUIRED = "browser_session_required"
    OAUTH_CONNECTION_MISSING = "oauth_connection_missing"
    OAUTH_CONNECTION_REVOKED = "oauth_connection_revoked"
    OAUTH_CONNECTION_ERROR = "oauth_connection_error"
    OAUTH_TOKEN_MISSING = "oauth_token_missing"
    OAUTH_TOKEN_EXPIRED = "oauth_token_expired"
    OTHER = "other"


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
    PENDING_REVIEW = "pending_review"
    REJECTED = "rejected"
    PUBLISHED = "published"
    UNPUBLISHED = "unpublished"


class MaterialCategory(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
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


class FactType(StrEnum):
    """权威事实库首批 12 类，顺序与业务口径一致。"""

    ORGANIZATION = "organization"
    BASE_ADDRESS = "base_address"
    CONTACT = "contact"
    COURSE_NAME = "course_name"
    COURSE_CONTENT = "course_content"
    COURSE_DURATION = "course_duration"
    COURSE_FEE = "course_fee"
    FACULTY = "faculty"
    TRAINING_RESULT = "training_result"
    EMPLOYMENT_SERVICE = "employment_service"
    PARTNER = "partner"
    CERTIFICATION = "certification"


class FactStatus(StrEnum):
    """事实状态机：草稿 → 待审 → 已批准 → 过期；驳回回草稿。"""

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    EXPIRED = "expired"


class FactVersionAction(StrEnum):
    CREATED = "created"
    REVISED = "revised"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class FactClaimVerdict(StrEnum):
    CORRECT = "correct"
    WRONG = "wrong"
    EXPIRED = "expired"
    UNCONFIRMED = "unconfirmed"


class CorrectionTaskStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class OAuthConnectionStatus(StrEnum):
    """平台 OAuth 连接状态：已连接、已撤销、刷新/授权异常。"""

    CONNECTED = "connected"
    REVOKED = "revoked"
    ERROR = "error"



class SiteModuleType(StrEnum):
    """K8 微站的 6 个内容模块；顺序即默认排序，命名固定以免前端多一套映射。"""

    HOME = "home"
    SERVICES = "services"
    NEWS = "news"
    DOWNLOAD = "download"
    POSTER = "poster"
    CARD = "card"


class HealthCheckStatus(StrEnum):
    """单项体检结论：只有「达成 / 未达成 / 无法计算」三档，没有总分。

    - pass 达成：分子 ≥ 目标；
    - fail 未达成：有分母、但分子不够；
    - unknown 无法计算：分母为 0（没有样本、没有渠道、没有引用），
      这种情况不给 0 分，因为「没有数据」和「做了但没达标」是两件事。
    """

    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class GenerationSource(StrEnum):
    """生成批次的选题来源：只接受「系统里已有缺口证据」的两类，不接受空手起题。"""

    OPPORTUNITY = "opportunity"
    QUESTION = "question"


class GenerationBatchStatus(StrEnum):
    """批次状态机：建好 → 跑（同步模板合成）→ 完成；中途失败进 failed。"""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class GenerationItemStatus(StrEnum):
    PENDING = "pending"
    DRAFTED = "drafted"
    FAILED = "failed"


class GenerationMode(StrEnum):
    """出稿方式：先只做模板合成，调模型必须显式开关（会花钱，不默认开）。"""

    TEMPLATE = "template"
    MODEL = "model"
