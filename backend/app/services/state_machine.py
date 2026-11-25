"""状态迁移的最小校验层：只定义合法边，不做持久化、不引入状态机框架。

约定：
- 同状态视为幂等，直接放行；
- 未列出的目标状态一律拒绝，抛 `TaskRejectedError`（409 task_rejected）；
- 终态没有出边，重试必须新建任务/样本 attempt，不能把旧记录改回 pending；
- 数据库 CHECK 只保证状态值合法，迁移合法性由本模块统一负责。
"""

from collections.abc import Mapping
from typing import Any

from app.core.errors import ConflictError, TaskRejectedError
from app.models.enums import (
    AttemptStatus,
    BudgetApprovalStatus,
    ChannelApprovalStatus,
    ChannelStatus,
    CitationReviewStatus,
    EncyclopediaStatus,
    EnrollmentStatus,
    FactStatus,
    GenerationBatchStatus,
    GenerationItemStatus,
    KnowledgeCandidateStatus,
    KnowledgeParseStatus,
    MetricStatus,
    ContentStatus,
    CorrectionTaskStatus,
    DistributionBatchStatus,
    FaqStatus,
    OAuthConnectionStatus,
    OutboxStatus,
    PagePublishStatus,
    AlertEventStatus,
    MediaOrderStatus,
    OpportunityStatus,
    OpportunitySuggestionStatus,
    PageApprovalStatus,
    PublishTaskStatus,
    QuestionCandidateStatus,
    QuestionStatus,
    QuoteStatus,
    RoundStatus,
    SampleStatus,
    SourceReviewStatus,
    TaskStatus,
)


TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    # pending -> failed 只用于人工登记登录阻断/超时等“未能发起有效采样”的失败；
    # 自动采集仍先由 worker 抢到 running，再写 failed。
    TaskStatus.PENDING: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.FAILED}),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.DONE,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.UNCERTAIN,
            TaskStatus.PENDING,
        }
    ),
    TaskStatus.UNCERTAIN: frozenset({TaskStatus.PENDING, TaskStatus.FAILED, TaskStatus.DONE}),
    TaskStatus.DONE: frozenset(),
    # 失败任务允许通过人工补录手测样本收敛到 done；只有人工确认过结果才走这条边。
    TaskStatus.FAILED: frozenset({TaskStatus.DONE}),
    TaskStatus.CANCELLED: frozenset(),
}

# 样本重分析：同一份回答重新打标，结果可以在 hit / miss / no_answer_surface 之间移动
# （规则或品牌词典变了就会变），这是派生重算，不是执行尝试；执行态仍走 SAMPLE_TRANSITIONS。
SAMPLE_REANALYSIS_TRANSITIONS: dict[SampleStatus, frozenset[SampleStatus]] = {
    SampleStatus.HIT: frozenset(
        {SampleStatus.MISS, SampleStatus.NO_ANSWER_SURFACE}
    ),
    SampleStatus.MISS: frozenset(
        {SampleStatus.HIT, SampleStatus.NO_ANSWER_SURFACE}
    ),
    SampleStatus.NO_ANSWER_SURFACE: frozenset(
        {SampleStatus.HIT, SampleStatus.MISS}
    ),
}

SAMPLE_TRANSITIONS: dict[SampleStatus, frozenset[SampleStatus]] = {
    SampleStatus.PENDING: frozenset({SampleStatus.RUNNING, SampleStatus.FAILED}),
    SampleStatus.RUNNING: frozenset(
        {
            SampleStatus.HIT,
            SampleStatus.MISS,
            SampleStatus.NO_ANSWER_SURFACE,
            SampleStatus.FAILED,
            SampleStatus.MANUAL_REVIEW,
        }
    ),
    SampleStatus.MANUAL_REVIEW: frozenset(
        {SampleStatus.HIT, SampleStatus.MISS, SampleStatus.FAILED}
    ),
    SampleStatus.HIT: frozenset(),
    SampleStatus.MISS: frozenset(),
    SampleStatus.NO_ANSWER_SURFACE: frozenset(),
    SampleStatus.FAILED: frozenset(),
}

ROUND_TRANSITIONS: dict[RoundStatus, frozenset[RoundStatus]] = {
    RoundStatus.PLANNING: frozenset({RoundStatus.RUNNING, RoundStatus.CLOSED}),
    RoundStatus.RUNNING: frozenset({RoundStatus.COMPLETED, RoundStatus.CLOSED}),
    RoundStatus.COMPLETED: frozenset({RoundStatus.CLOSED}),
    RoundStatus.CLOSED: frozenset(),
}

PUBLISH_TASK_TRANSITIONS: dict[PublishTaskStatus, frozenset[PublishTaskStatus]] = {
    PublishTaskStatus.PENDING: frozenset(
        {
            PublishTaskStatus.PUBLISHING,
            PublishTaskStatus.UNKNOWN,
            PublishTaskStatus.FAILED,
            PublishTaskStatus.NEEDS_REVIEW,
            PublishTaskStatus.CANCELLED,
        }
    ),
    PublishTaskStatus.NEEDS_REVIEW: frozenset(
        {
            PublishTaskStatus.PUBLISHING,
            PublishTaskStatus.UNKNOWN,
            PublishTaskStatus.FAILED,
            PublishTaskStatus.CANCELLED,
        }
    ),
    PublishTaskStatus.PUBLISHING: frozenset(
        {PublishTaskStatus.PUBLISHED, PublishTaskStatus.FAILED, PublishTaskStatus.UNKNOWN}
    ),
    PublishTaskStatus.UNKNOWN: frozenset(
        {PublishTaskStatus.PENDING, PublishTaskStatus.PUBLISHED}
    ),
    PublishTaskStatus.PUBLISHED: frozenset(),
    PublishTaskStatus.FAILED: frozenset(),
    PublishTaskStatus.CANCELLED: frozenset(),
}

# 内容状态迁移表：submit / review 写入点经 ensure_content_transition 强制；枚举全部保留，不收敛。
# pending_publish 与 scheduled 并存，用于兼容“待发布”字面口径与既有排期状态。
CONTENT_TRANSITIONS: dict[ContentStatus, frozenset[ContentStatus]] = {
    ContentStatus.DRAFT: frozenset(
        {ContentStatus.PENDING_REVIEW, ContentStatus.ARCHIVED}
    ),
    ContentStatus.PENDING_REVIEW: frozenset(
        {ContentStatus.APPROVED, ContentStatus.REJECTED, ContentStatus.DRAFT, ContentStatus.ARCHIVED}
    ),
    ContentStatus.APPROVED: frozenset(
        {
            ContentStatus.SCHEDULED,
            ContentStatus.PENDING_PUBLISH,
            ContentStatus.PUBLISHED,
            ContentStatus.NEEDS_ATTENTION,
            ContentStatus.ARCHIVED,
            ContentStatus.PENDING_REVIEW,
            # 改稿回草稿：内容被改过就必须重新审核，不能沿用旧的通过状态
            ContentStatus.DRAFT,
        }
    ),
    ContentStatus.REJECTED: frozenset(
        {ContentStatus.DRAFT, ContentStatus.PENDING_REVIEW, ContentStatus.ARCHIVED}
    ),
    ContentStatus.PENDING_PUBLISH: frozenset(
        {
            ContentStatus.PUBLISHED,
            ContentStatus.NEEDS_ATTENTION,
            ContentStatus.ARCHIVED,
            ContentStatus.DRAFT,
        }
    ),
    ContentStatus.PUBLISHED: frozenset(
        {
            ContentStatus.NEEDS_ATTENTION,
            ContentStatus.ARCHIVED,
            ContentStatus.PENDING_REVIEW,
            ContentStatus.DRAFT,
        }
    ),
    ContentStatus.NEEDS_ATTENTION: frozenset(
        {
            ContentStatus.PENDING_PUBLISH,
            ContentStatus.PUBLISHED,
            ContentStatus.ARCHIVED,
            ContentStatus.DRAFT,
        }
    ),
    ContentStatus.ARCHIVED: frozenset(),
}


# 投喂批次：blocked ↔ ready 由预检重算决定（预检是幂等重算，不是业务推进），
# 只有 ready 能确认投喂；确认后 dispatched 是终态——要再投一轮就新建批次。
DISTRIBUTION_BATCH_TRANSITIONS: dict[DistributionBatchStatus, frozenset[DistributionBatchStatus]] = {
    DistributionBatchStatus.BLOCKED: frozenset({DistributionBatchStatus.READY}),
    DistributionBatchStatus.READY: frozenset({DistributionBatchStatus.DISPATCHED, DistributionBatchStatus.BLOCKED}),
    DistributionBatchStatus.DISPATCHED: frozenset(),
}


# FAQ：提交审核 → 通过/驳回；已上架必须先下架才能再提审（避免反复改动线上问答）。
# 删除/恢复由 `deleted_at` 表达，不写在状态边里（两者都允许从任意状态发生）。
FAQ_TRANSITIONS: dict[FaqStatus, frozenset[FaqStatus]] = {
    # 删除是一条旁路（软删后状态统一落 unpublished），不改变审核语义，所以任何
    # 未删除状态都能删；恢复时回草稿重走审核，不直接跳回已发布。
    FaqStatus.DRAFT: frozenset({FaqStatus.PENDING_REVIEW, FaqStatus.UNPUBLISHED}),
    FaqStatus.REJECTED: frozenset({FaqStatus.PENDING_REVIEW, FaqStatus.UNPUBLISHED}),
    FaqStatus.PENDING_REVIEW: frozenset(
        {FaqStatus.PUBLISHED, FaqStatus.REJECTED, FaqStatus.UNPUBLISHED}
    ),
    FaqStatus.PUBLISHED: frozenset({FaqStatus.UNPUBLISHED}),
    FaqStatus.UNPUBLISHED: frozenset({FaqStatus.PENDING_REVIEW, FaqStatus.DRAFT}),
}

# 报价：待审批 → 通过/驳回/撤回；通过或驳回后锁定，只能撤回，不能改判。
QUOTE_TRANSITIONS: dict[QuoteStatus, frozenset[QuoteStatus]] = {
    QuoteStatus.PENDING: frozenset(
        {QuoteStatus.APPROVED, QuoteStatus.REJECTED, QuoteStatus.WITHDRAWN}
    ),
    QuoteStatus.APPROVED: frozenset({QuoteStatus.WITHDRAWN}),
    QuoteStatus.REJECTED: frozenset({QuoteStatus.WITHDRAWN}),
    QuoteStatus.WITHDRAWN: frozenset(),
}

# 信源复核：待复核 → 判定 / 忽略；判过还能改判成忽略，但不会回到待复核。
SOURCE_REVIEW_TRANSITIONS: dict[SourceReviewStatus, frozenset[SourceReviewStatus]] = {
    SourceReviewStatus.PENDING: frozenset(
        {SourceReviewStatus.CLASSIFIED, SourceReviewStatus.IGNORED}
    ),
    SourceReviewStatus.CLASSIFIED: frozenset({SourceReviewStatus.IGNORED}),
    SourceReviewStatus.IGNORED: frozenset(),
}

# 页面审批：待审批 → 批准/驳回；只有已批准能被撤销（撤销后不可再批，须重新提交）。
PAGE_APPROVAL_TRANSITIONS: dict[PageApprovalStatus, frozenset[PageApprovalStatus]] = {
    PageApprovalStatus.PENDING: frozenset(
        {PageApprovalStatus.APPROVED, PageApprovalStatus.REJECTED}
    ),
    PageApprovalStatus.APPROVED: frozenset({PageApprovalStatus.REVOKED}),
    PageApprovalStatus.REJECTED: frozenset(),
    PageApprovalStatus.REVOKED: frozenset(),
}

# 题目：草稿 → 启用 → 归档；归档可再启用（搜索词会复活，历史监测数据保留）。
# 原来这套规则以 `_ALLOWED_TRANSITIONS` 私有常量存在于 api/questions.py。
QUESTION_TRANSITIONS: dict[QuestionStatus, frozenset[QuestionStatus]] = {
    QuestionStatus.DRAFT: frozenset({QuestionStatus.ACTIVE}),
    QuestionStatus.ACTIVE: frozenset({QuestionStatus.ARCHIVED}),
    QuestionStatus.ARCHIVED: frozenset({QuestionStatus.ACTIVE}),
}

# 预算审批：待审批 → 通过/驳回，两者都是终态（要改金额得重新提申请）。
BUDGET_APPROVAL_TRANSITIONS: dict[BudgetApprovalStatus, frozenset[BudgetApprovalStatus]] = {
    BudgetApprovalStatus.PENDING: frozenset(
        {BudgetApprovalStatus.APPROVED, BudgetApprovalStatus.REJECTED}
    ),
    BudgetApprovalStatus.APPROVED: frozenset(),
    BudgetApprovalStatus.REJECTED: frozenset(),
}

# 事实纠错任务：待认领 → 处理中 → 已解决/已忽略。
# 允许回退：处理中可退回待认领（换人）；已解决可重开（发现复核结论错）；已忽略可重开。
CORRECTION_TASK_TRANSITIONS: dict[CorrectionTaskStatus, frozenset[CorrectionTaskStatus]] = {
    CorrectionTaskStatus.OPEN: frozenset(
        {CorrectionTaskStatus.IN_PROGRESS, CorrectionTaskStatus.DISMISSED}
    ),
    CorrectionTaskStatus.IN_PROGRESS: frozenset(
        {
            CorrectionTaskStatus.OPEN,
            CorrectionTaskStatus.RESOLVED,
            CorrectionTaskStatus.DISMISSED,
        }
    ),
    CorrectionTaskStatus.RESOLVED: frozenset({CorrectionTaskStatus.IN_PROGRESS}),
    CorrectionTaskStatus.DISMISSED: frozenset({CorrectionTaskStatus.OPEN}),
}

# 机会：待处理 → 处理中 → 完成/放弃；完成与放弃都可重开（结论会变）。
OPPORTUNITY_TRANSITIONS: dict[OpportunityStatus, frozenset[OpportunityStatus]] = {
    OpportunityStatus.OPEN: frozenset(
        {OpportunityStatus.IN_PROGRESS, OpportunityStatus.DONE, OpportunityStatus.DISMISSED}
    ),
    OpportunityStatus.IN_PROGRESS: frozenset(
        {OpportunityStatus.OPEN, OpportunityStatus.DONE, OpportunityStatus.DISMISSED}
    ),
    OpportunityStatus.DONE: frozenset({OpportunityStatus.IN_PROGRESS}),
    OpportunityStatus.DISMISSED: frozenset({OpportunityStatus.OPEN}),
}

# 媒体订单（第三方媒体代发）：草稿 → 已提交 → 已确认 → 已发布；
# 提交后可失败，草稿/已确认可取消，已发布是终态（对外发出去的事实不该被撤销）。
MEDIA_ORDER_TRANSITIONS: dict[MediaOrderStatus, frozenset[MediaOrderStatus]] = {
    # 人工渠道没有「提交给外部系统」这一步：线下谈定后由人直接把草稿标成已确认，
    # 所以 DRAFT -> CONFIRMED 是人工渠道的正常路径，不是绕过流程。
    MediaOrderStatus.DRAFT: frozenset(
        {
            MediaOrderStatus.SUBMITTED,
            MediaOrderStatus.CONFIRMED,
            MediaOrderStatus.CANCELLED,
            MediaOrderStatus.FAILED,
        }
    ),
    MediaOrderStatus.SUBMITTED: frozenset(
        {
            MediaOrderStatus.CONFIRMED,
            MediaOrderStatus.FAILED,
            MediaOrderStatus.PUBLISHED,
            MediaOrderStatus.CANCELLED,
        }
    ),
    MediaOrderStatus.CONFIRMED: frozenset(
        {MediaOrderStatus.PUBLISHED, MediaOrderStatus.FAILED, MediaOrderStatus.CANCELLED}
    ),
    MediaOrderStatus.PUBLISHED: frozenset(),
    MediaOrderStatus.FAILED: frozenset({MediaOrderStatus.DRAFT, MediaOrderStatus.SUBMITTED}),
    MediaOrderStatus.CANCELLED: frozenset({MediaOrderStatus.DRAFT}),
}

# 告警事件：打开 → 已确认 → 已解决；已解决可重开（同一现象再出现）。
# 已确认不能直接跳已解决以外的状态，避免"点一下就算处理完"。
ALERT_EVENT_TRANSITIONS: dict[AlertEventStatus, frozenset[AlertEventStatus]] = {
    AlertEventStatus.OPEN: frozenset(
        {AlertEventStatus.ACKNOWLEDGED, AlertEventStatus.RESOLVED}
    ),
    AlertEventStatus.ACKNOWLEDGED: frozenset(
        {AlertEventStatus.OPEN, AlertEventStatus.RESOLVED}
    ),
    AlertEventStatus.RESOLVED: frozenset({AlertEventStatus.OPEN}),
}

# 机会建议：系统按规则算出的候选，只能人接或人弃；被采纳/弃掉的都可回退成待处理
# （规则或数据变了要能重算，所以不给终态）。
OPPORTUNITY_SUGGESTION_TRANSITIONS: dict[
    OpportunitySuggestionStatus, frozenset[OpportunitySuggestionStatus]
] = {
    OpportunitySuggestionStatus.SUGGESTED: frozenset(
        {OpportunitySuggestionStatus.ACCEPTED, OpportunitySuggestionStatus.DISMISSED}
    ),
    OpportunitySuggestionStatus.ACCEPTED: frozenset({OpportunitySuggestionStatus.SUGGESTED}),
    OpportunitySuggestionStatus.DISMISSED: frozenset({OpportunitySuggestionStatus.SUGGESTED}),
}

# 渠道台账状态（不是准入 `approval_status`，那是另一条待审/通过/驳回的线）：
# - candidate：刚登记或从行业预设带出来的候选渠道；
# - review_pending：待归类的未知域名，等人工确认它是哪类信源；
# - observed：AI 回答里引用了它的域名（只说明它被引用，不代表我们发过稿）；
# - published：我们真的往这个渠道发过稿（发布回执结案推进的终态）。
# published 没有出边：一旦「我们发过」这件事成立，就不该被降级成「只是被引用」。
CHANNEL_TRANSITIONS: dict[ChannelStatus, frozenset[ChannelStatus]] = {
    ChannelStatus.CANDIDATE: frozenset(
        {ChannelStatus.REVIEW_PENDING, ChannelStatus.OBSERVED, ChannelStatus.PUBLISHED}
    ),
    ChannelStatus.REVIEW_PENDING: frozenset(
        {ChannelStatus.CANDIDATE, ChannelStatus.OBSERVED, ChannelStatus.PUBLISHED}
    ),
    ChannelStatus.OBSERVED: frozenset(
        {ChannelStatus.REVIEW_PENDING, ChannelStatus.PUBLISHED}
    ),
    ChannelStatus.PUBLISHED: frozenset(),
}

# 执行尝试（Attempt）：一次领取一条记录。外部请求发出后结果未知，只能标 uncertain，
# 不允许自动重发；因此 dispatching / succeeded 都能落到 uncertain。
ATTEMPT_TRANSITIONS: dict[AttemptStatus, frozenset[AttemptStatus]] = {
    AttemptStatus.CLAIMED: frozenset(
        {
            AttemptStatus.DISPATCHING,
            AttemptStatus.LEASE_EXPIRED,
            AttemptStatus.RATE_LIMITED,
            AttemptStatus.FAILED,
        }
    ),
    AttemptStatus.DISPATCHING: frozenset(
        {
            AttemptStatus.SUCCEEDED,
            AttemptStatus.FAILED,
            AttemptStatus.RATE_LIMITED,
            AttemptStatus.UNCERTAIN,
        }
    ),
    AttemptStatus.SUCCEEDED: frozenset({AttemptStatus.UNCERTAIN}),
    AttemptStatus.FAILED: frozenset(),
    AttemptStatus.RATE_LIMITED: frozenset(),
    AttemptStatus.LEASE_EXPIRED: frozenset(),
    AttemptStatus.UNCERTAIN: frozenset(),
}

# 百科词条：草稿 ⇄ 待审 ⇄ 已发布/已驳回；驳回后可改回草稿再提交。
ENCYCLOPEDIA_TRANSITIONS: dict[EncyclopediaStatus, frozenset[EncyclopediaStatus]] = {
    EncyclopediaStatus.DRAFT: frozenset({EncyclopediaStatus.PENDING_REVIEW}),
    EncyclopediaStatus.PENDING_REVIEW: frozenset(
        {EncyclopediaStatus.PUBLISHED, EncyclopediaStatus.REJECTED}
    ),
    EncyclopediaStatus.REJECTED: frozenset(
        {EncyclopediaStatus.DRAFT, EncyclopediaStatus.PENDING_REVIEW}
    ),
    EncyclopediaStatus.PUBLISHED: frozenset(),
}

# 发件箱事件：pending 只能到 dispatched（送达）或 failed（超次数进死信），两者都是终态。
OUTBOX_TRANSITIONS: dict[OutboxStatus, frozenset[OutboxStatus]] = {
    OutboxStatus.PENDING: frozenset({OutboxStatus.DISPATCHED, OutboxStatus.FAILED}),
    OutboxStatus.DISPATCHED: frozenset(),
    OutboxStatus.FAILED: frozenset(),
}

# 平台 OAuth 连接：connected / error 可互相转换（刷新失败进 error，刷新成功回 connected），
# 撤销是终态；但撤销后重新授权是允许的（用户重新走一次 OAuth），所以 revoked → connected 有边。
OAUTH_CONNECTION_TRANSITIONS: dict[
    OAuthConnectionStatus, frozenset[OAuthConnectionStatus]
] = {
    OAuthConnectionStatus.CONNECTED: frozenset(
        {OAuthConnectionStatus.ERROR, OAuthConnectionStatus.REVOKED}
    ),
    OAuthConnectionStatus.ERROR: frozenset(
        {OAuthConnectionStatus.CONNECTED, OAuthConnectionStatus.REVOKED}
    ),
    OAuthConnectionStatus.REVOKED: frozenset({OAuthConnectionStatus.CONNECTED}),
}

# 生成批次：queued → running → completed；失败可重跑，已完成也可重跑（重跑是显式的业务动作）。
GENERATION_BATCH_TRANSITIONS: dict[
    GenerationBatchStatus, frozenset[GenerationBatchStatus]
] = {
    GenerationBatchStatus.QUEUED: frozenset({GenerationBatchStatus.RUNNING}),
    GenerationBatchStatus.RUNNING: frozenset(
        {GenerationBatchStatus.COMPLETED, GenerationBatchStatus.FAILED}
    ),
    GenerationBatchStatus.FAILED: frozenset({GenerationBatchStatus.RUNNING}),
    GenerationBatchStatus.COMPLETED: frozenset({GenerationBatchStatus.RUNNING}),
}

# 生成条目：pending → drafted / failed；草稿失败可重试，已出稿不再回退。
GENERATION_ITEM_TRANSITIONS: dict[
    GenerationItemStatus, frozenset[GenerationItemStatus]
] = {
    GenerationItemStatus.PENDING: frozenset(
        {GenerationItemStatus.DRAFTED, GenerationItemStatus.FAILED}
    ),
    GenerationItemStatus.DRAFTED: frozenset(),
    GenerationItemStatus.FAILED: frozenset({GenerationItemStatus.PENDING}),
}

# 事实（Fact，字段是 approval_status）：草稿 → 待审 → 已批准 → 过期；改内容或驳回都回草稿。
FACT_TRANSITIONS: dict[FactStatus, frozenset[FactStatus]] = {
    FactStatus.DRAFT: frozenset({FactStatus.PENDING_REVIEW}),
    FactStatus.PENDING_REVIEW: frozenset({FactStatus.APPROVED, FactStatus.DRAFT}),
    FactStatus.APPROVED: frozenset({FactStatus.DRAFT, FactStatus.EXPIRED}),
    FactStatus.EXPIRED: frozenset({FactStatus.DRAFT}),
}

# 页面发布状态：草稿 ⇄ 已发布 ⇄ 已下线，三态互转都合法（下线后可重新发布）。
PAGE_PUBLISH_TRANSITIONS: dict[PagePublishStatus, frozenset[PagePublishStatus]] = {
    PagePublishStatus.DRAFT: frozenset(
        {PagePublishStatus.PUBLISHED, PagePublishStatus.OFFLINE}
    ),
    PagePublishStatus.PUBLISHED: frozenset(
        {PagePublishStatus.DRAFT, PagePublishStatus.OFFLINE}
    ),
    PagePublishStatus.OFFLINE: frozenset(
        {PagePublishStatus.DRAFT, PagePublishStatus.PUBLISHED}
    ),
}

# 指标口径：启用 ⇄ 停用（停用要落 effective_to，重新启用要清掉）。
METRIC_TRANSITIONS: dict[MetricStatus, frozenset[MetricStatus]] = {
    MetricStatus.ACTIVE: frozenset({MetricStatus.RETIRED}),
    MetricStatus.RETIRED: frozenset({MetricStatus.ACTIVE}),
}

# 线索转化：未知 → 已联系 → 已报名；任一步都可判流失，流失后可重新联系。
ENROLLMENT_TRANSITIONS: dict[EnrollmentStatus, frozenset[EnrollmentStatus]] = {
    EnrollmentStatus.UNKNOWN: frozenset(
        {EnrollmentStatus.CONTACTED, EnrollmentStatus.ENROLLED, EnrollmentStatus.LOST}
    ),
    EnrollmentStatus.CONTACTED: frozenset(
        {EnrollmentStatus.ENROLLED, EnrollmentStatus.LOST, EnrollmentStatus.UNKNOWN}
    ),
    EnrollmentStatus.ENROLLED: frozenset({EnrollmentStatus.LOST}),
    EnrollmentStatus.LOST: frozenset(
        {EnrollmentStatus.CONTACTED, EnrollmentStatus.UNKNOWN}
    ),
}

# 引用复核（字段 review_status）：auto 是机器判的起点，人工只能往两个人工态改；
# 人工态之间可以互相纠正，但不能再退回 auto（否则自动判定会覆盖人的结论）。
CITATION_REVIEW_TRANSITIONS: dict[
    CitationReviewStatus, frozenset[CitationReviewStatus]
] = {
    CitationReviewStatus.AUTO: frozenset(
        {
            CitationReviewStatus.MANUAL_CONFIRMED,
            CitationReviewStatus.MANUAL_REJECTED,
        }
    ),
    CitationReviewStatus.MANUAL_CONFIRMED: frozenset(
        {
            CitationReviewStatus.MANUAL_CONFIRMED,
            CitationReviewStatus.MANUAL_REJECTED,
        }
    ),
    CitationReviewStatus.MANUAL_REJECTED: frozenset(
        {
            CitationReviewStatus.MANUAL_CONFIRMED,
            CitationReviewStatus.MANUAL_REJECTED,
        }
    ),
}

# 候选问句：规则/导入派生出来待定 → 采纳进题库或否掉；否掉的允许回到待定重评。
QUESTION_CANDIDATE_TRANSITIONS: dict[
    QuestionCandidateStatus, frozenset[QuestionCandidateStatus]
] = {
    QuestionCandidateStatus.PENDING: frozenset(
        {QuestionCandidateStatus.ACCEPTED, QuestionCandidateStatus.REJECTED}
    ),
    QuestionCandidateStatus.ACCEPTED: frozenset(),
    QuestionCandidateStatus.REJECTED: frozenset({QuestionCandidateStatus.PENDING}),
}

# 知识库文档解析：待解析 → 解析中 → 就绪/失败/不支持；失败可重试回待解析。
KNOWLEDGE_PARSE_TRANSITIONS: dict[
    KnowledgeParseStatus, frozenset[KnowledgeParseStatus]
] = {
    KnowledgeParseStatus.PENDING: frozenset({KnowledgeParseStatus.PARSING}),
    KnowledgeParseStatus.PARSING: frozenset(
        {
            KnowledgeParseStatus.READY,
            KnowledgeParseStatus.FAILED,
            KnowledgeParseStatus.UNSUPPORTED,
        }
    ),
    KnowledgeParseStatus.READY: frozenset({KnowledgeParseStatus.PENDING}),
    KnowledgeParseStatus.FAILED: frozenset({KnowledgeParseStatus.PENDING}),
    KnowledgeParseStatus.UNSUPPORTED: frozenset(),
}

# 知识条目候选：建议 → 采纳/驳回；驳回后允许回到建议重评。采纳为终态。
KNOWLEDGE_CANDIDATE_TRANSITIONS: dict[
    KnowledgeCandidateStatus, frozenset[KnowledgeCandidateStatus]
] = {
    KnowledgeCandidateStatus.SUGGESTED: frozenset(
        {KnowledgeCandidateStatus.ACCEPTED, KnowledgeCandidateStatus.REJECTED}
    ),
    KnowledgeCandidateStatus.ACCEPTED: frozenset(),
    KnowledgeCandidateStatus.REJECTED: frozenset({KnowledgeCandidateStatus.SUGGESTED}),
}

# 渠道准入审批（字段 approval_status）：待审 → 通过/驳回；驳回后可重新提交回待审。
CHANNEL_APPROVAL_TRANSITIONS: dict[
    ChannelApprovalStatus, frozenset[ChannelApprovalStatus]
] = {
    ChannelApprovalStatus.PENDING_REVIEW: frozenset(
        {ChannelApprovalStatus.APPROVED, ChannelApprovalStatus.REJECTED}
    ),
    ChannelApprovalStatus.APPROVED: frozenset(),
    ChannelApprovalStatus.REJECTED: frozenset({ChannelApprovalStatus.PENDING_REVIEW}),
}


def can_transition(
    transitions: Mapping[Any, frozenset[Any]],
    current: Any,
    target: Any,
) -> bool:
    """只判断，不抛异常；供查询/预检使用。"""
    if current == target:
        return True
    return target in transitions.get(current, frozenset())


def ensure_transition(
    *,
    resource: str,
    transitions: Mapping[Any, frozenset[Any]],
    current: Any,
    target: Any,
    allow_same: bool = True,
) -> Any:
    """合法则返回 target，非法抛 409 task_rejected；默认同状态幂等放行。"""
    if current == target:
        if allow_same:
            return target
        raise TaskRejectedError(f"{resource} 已处于 {current}，不允许重复提交")
    if not can_transition(transitions, current, target):
        raise TaskRejectedError(f"{resource} 状态 {current} 不允许迁移到 {target}")
    return target


def ensure_task_transition(current: TaskStatus, target: TaskStatus) -> TaskStatus:
    return ensure_transition(
        resource="monitoring_task",
        transitions=TASK_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_sample_transition(current: SampleStatus, target: SampleStatus) -> SampleStatus:
    return ensure_transition(
        resource="monitoring_sample",
        transitions=SAMPLE_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_round_transition(current: RoundStatus, target: RoundStatus) -> RoundStatus:
    return ensure_transition(
        resource="monitoring_round",
        transitions=ROUND_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_publish_transition(
    current: PublishTaskStatus, target: PublishTaskStatus
) -> PublishTaskStatus:
    return ensure_transition(
        resource="publish_task",
        transitions=PUBLISH_TASK_TRANSITIONS,
        current=current,
        target=target,
        allow_same=False,
    )


def ensure_content_transition(current: ContentStatus, target: ContentStatus) -> ContentStatus:
    return ensure_transition(
        resource="content_version",
        transitions=CONTENT_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_distribution_precheck_transition(
    current: DistributionBatchStatus, target: DistributionBatchStatus
) -> DistributionBatchStatus:
    """预检结论重写：派生判定，允许同值重复写（重算一次结果不变不该报错）。

    与 ensure_distribution_transition 的区别就在这里：后者用于「提交投喂」这个人为动作，
    同值重复提交通常意味着重复点了按钮，要拦。判定与动作混用一条口径会误伤重算。
    """
    return ensure_transition(
        resource="distribution_batch",
        transitions=DISTRIBUTION_BATCH_TRANSITIONS,
        current=current,
        target=target,
        allow_same=True,
    )


def ensure_distribution_transition(
    current: DistributionBatchStatus, target: DistributionBatchStatus
) -> DistributionBatchStatus:
    """批次确认投喂必须经这里，禁止 api 里手写 `batch.status = ...`。

    注意：`blocked ↔ ready` 是预检重算的结论，允许双向；`dispatched` 没有出边。
    """
    return ensure_transition(
        resource="distribution_batch",
        transitions=DISTRIBUTION_BATCH_TRANSITIONS,
        current=current,
        target=target,
        allow_same=False,
    )


def ensure_faq_transition(current: FaqStatus, target: FaqStatus) -> FaqStatus:
    return ensure_transition(
        resource="faq",
        transitions=FAQ_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_quote_transition(current: QuoteStatus, target: QuoteStatus) -> QuoteStatus:
    return ensure_transition(
        resource="media_quote",
        transitions=QUOTE_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_source_review_transition(
    current: SourceReviewStatus, target: SourceReviewStatus
) -> SourceReviewStatus:
    return ensure_transition(
        resource="citation_source_review",
        transitions=SOURCE_REVIEW_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_page_approval_transition(
    current: PageApprovalStatus, target: PageApprovalStatus
) -> PageApprovalStatus:
    return ensure_transition(
        resource="page_approval",
        transitions=PAGE_APPROVAL_TRANSITIONS,
        current=current,
        target=target,
        allow_same=False,
    )


def ensure_question_transition(
    current: QuestionStatus, target: QuestionStatus
) -> QuestionStatus:
    """题目状态迁移。

    非法迁移沿用既有 API 错误码 `question_status_conflict`（409），
    因为前端与既有用例按这个码判断「状态冲突」，不能因为收口状态机就换码。
    """
    if not can_transition(QUESTION_TRANSITIONS, current, target):
        raise ConflictError(
            f"题目状态不允许从 {current.value} 变为 {target.value}",
            code="question_status_conflict",
        )
    return target


def ensure_budget_approval_transition(
    current: BudgetApprovalStatus, target: BudgetApprovalStatus
) -> BudgetApprovalStatus:
    return ensure_transition(
        resource="budget_approval",
        transitions=BUDGET_APPROVAL_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_correction_task_transition(
    current: CorrectionTaskStatus, target: CorrectionTaskStatus
) -> CorrectionTaskStatus:
    return ensure_transition(
        resource="correction_task",
        transitions=CORRECTION_TASK_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_channel_transition(
    current: ChannelStatus, target: ChannelStatus
) -> ChannelStatus:
    return ensure_transition(
        resource="channel",
        transitions=CHANNEL_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_question_candidate_transition(
    current: QuestionCandidateStatus, target: QuestionCandidateStatus
) -> QuestionCandidateStatus:
    return ensure_transition(
        resource="question_candidate",
        transitions=QUESTION_CANDIDATE_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_fact_transition(current: FactStatus, target: FactStatus) -> FactStatus:
    return ensure_transition(
        resource="fact",
        transitions=FACT_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_page_publish_transition(
    current: PagePublishStatus, target: PagePublishStatus
) -> PagePublishStatus:
    return ensure_transition(
        resource="public_page",
        transitions=PAGE_PUBLISH_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_metric_transition(current: MetricStatus, target: MetricStatus) -> MetricStatus:
    return ensure_transition(
        resource="metric_definition",
        transitions=METRIC_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_enrollment_transition(
    current: EnrollmentStatus, target: EnrollmentStatus
) -> EnrollmentStatus:
    return ensure_transition(
        resource="lead",
        transitions=ENROLLMENT_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_citation_review_transition(
    current: CitationReviewStatus, target: CitationReviewStatus
) -> CitationReviewStatus:
    return ensure_transition(
        resource="monitoring_citation",
        transitions=CITATION_REVIEW_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_channel_approval_transition(
    current: ChannelApprovalStatus, target: ChannelApprovalStatus
) -> ChannelApprovalStatus:
    return ensure_transition(
        resource="channel_approval",
        transitions=CHANNEL_APPROVAL_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_attempt_transition(current: AttemptStatus, target: AttemptStatus) -> AttemptStatus:
    return ensure_transition(
        resource="monitoring_attempt",
        transitions=ATTEMPT_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_encyclopedia_transition(
    current: EncyclopediaStatus, target: EncyclopediaStatus
) -> EncyclopediaStatus:
    return ensure_transition(
        resource="encyclopedia_entry",
        transitions=ENCYCLOPEDIA_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_outbox_transition(current: OutboxStatus, target: OutboxStatus) -> OutboxStatus:
    return ensure_transition(
        resource="outbox_event",
        transitions=OUTBOX_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_oauth_connection_transition(
    current: OAuthConnectionStatus, target: OAuthConnectionStatus
) -> OAuthConnectionStatus:
    return ensure_transition(
        resource="oauth_connection",
        transitions=OAUTH_CONNECTION_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_generation_batch_transition(
    current: GenerationBatchStatus, target: GenerationBatchStatus
) -> GenerationBatchStatus:
    return ensure_transition(
        resource="generation_batch",
        transitions=GENERATION_BATCH_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_generation_item_transition(
    current: GenerationItemStatus, target: GenerationItemStatus
) -> GenerationItemStatus:
    return ensure_transition(
        resource="generation_item",
        transitions=GENERATION_ITEM_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_alert_event_transition(
    current: AlertEventStatus, target: AlertEventStatus
) -> AlertEventStatus:
    return ensure_transition(
        resource="alert_event",
        transitions=ALERT_EVENT_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_opportunity_transition(
    current: OpportunityStatus, target: OpportunityStatus
) -> OpportunityStatus:
    return ensure_transition(
        resource="opportunity",
        transitions=OPPORTUNITY_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_sample_reanalysis_transition(
    current: SampleStatus, target: SampleStatus
) -> SampleStatus:
    """重分析写回结果：只允许在可分析结果之间移动，其它状态仍走 ensure_sample_transition。"""
    return ensure_transition(
        resource="monitoring_sample_reanalysis",
        transitions=SAMPLE_REANALYSIS_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_media_order_transition(
    current: MediaOrderStatus, target: MediaOrderStatus
) -> MediaOrderStatus:
    return ensure_transition(
        resource="media_order",
        transitions=MEDIA_ORDER_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_opportunity_suggestion_transition(
    current: OpportunitySuggestionStatus, target: OpportunitySuggestionStatus
) -> OpportunitySuggestionStatus:
    return ensure_transition(
        resource="opportunity_suggestion",
        transitions=OPPORTUNITY_SUGGESTION_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_knowledge_parse_transition(
    current: KnowledgeParseStatus, target: KnowledgeParseStatus
) -> KnowledgeParseStatus:
    return ensure_transition(
        resource="knowledge_document",
        transitions=KNOWLEDGE_PARSE_TRANSITIONS,
        current=current,
        target=target,
    )


def ensure_knowledge_candidate_transition(
    current: KnowledgeCandidateStatus, target: KnowledgeCandidateStatus
) -> KnowledgeCandidateStatus:
    return ensure_transition(
        resource="knowledge_candidate",
        transitions=KNOWLEDGE_CANDIDATE_TRANSITIONS,
        current=current,
        target=target,
    )
