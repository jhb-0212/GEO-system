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
    BudgetApprovalStatus,
    ChannelStatus,
    ContentStatus,
    CorrectionTaskStatus,
    DistributionBatchStatus,
    FaqStatus,
    OpportunityStatus,
    PageApprovalStatus,
    PublishTaskStatus,
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
        }
    ),
    ContentStatus.REJECTED: frozenset(
        {ContentStatus.DRAFT, ContentStatus.PENDING_REVIEW, ContentStatus.ARCHIVED}
    ),
    ContentStatus.PENDING_PUBLISH: frozenset(
        {ContentStatus.PUBLISHED, ContentStatus.NEEDS_ATTENTION, ContentStatus.ARCHIVED}
    ),
    ContentStatus.PUBLISHED: frozenset(
        {
            ContentStatus.NEEDS_ATTENTION,
            ContentStatus.ARCHIVED,
            ContentStatus.PENDING_REVIEW,
        }
    ),
    ContentStatus.NEEDS_ATTENTION: frozenset(
        {ContentStatus.PENDING_PUBLISH, ContentStatus.PUBLISHED, ContentStatus.ARCHIVED}
    ),
    ContentStatus.ARCHIVED: frozenset(),
}


# 投喂批次：blocked ↔ ready 由预检重算决定（预检是幂等重算，不是业务推进），
# 只有 ready 能确认投喂；确认后 dispatched 是终态——要再投一轮就新建批次。
DISTRIBUTION_TRANSITIONS: dict[DistributionBatchStatus, frozenset[DistributionBatchStatus]] = {
    DistributionBatchStatus.BLOCKED: frozenset({DistributionBatchStatus.READY}),
    DistributionBatchStatus.READY: frozenset({DistributionBatchStatus.DISPATCHED, DistributionBatchStatus.BLOCKED}),
    DistributionBatchStatus.DISPATCHED: frozenset(),
}


# FAQ：提交审核 → 通过/驳回；已上架必须先下架才能再提审（避免反复改动线上问答）。
# 删除/恢复由 `deleted_at` 表达，不写在状态边里（两者都允许从任意状态发生）。
FAQ_TRANSITIONS: dict[FaqStatus, frozenset[FaqStatus]] = {
    FaqStatus.DRAFT: frozenset({FaqStatus.PENDING_REVIEW}),
    FaqStatus.REJECTED: frozenset({FaqStatus.PENDING_REVIEW}),
    FaqStatus.PENDING_REVIEW: frozenset({FaqStatus.PUBLISHED, FaqStatus.REJECTED}),
    FaqStatus.PUBLISHED: frozenset({FaqStatus.UNPUBLISHED}),
    FaqStatus.UNPUBLISHED: frozenset({FaqStatus.PENDING_REVIEW}),
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


def ensure_distribution_transition(
    current: DistributionBatchStatus, target: DistributionBatchStatus
) -> DistributionBatchStatus:
    """批次确认投喂必须经这里，禁止 api 里手写 `batch.status = ...`。

    注意：`blocked ↔ ready` 是预检重算的结论，允许双向；`dispatched` 没有出边。
    """
    return ensure_transition(
        resource="distribution_batch",
        transitions=DISTRIBUTION_TRANSITIONS,
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


def ensure_opportunity_transition(
    current: OpportunityStatus, target: OpportunityStatus
) -> OpportunityStatus:
    return ensure_transition(
        resource="opportunity",
        transitions=OPPORTUNITY_TRANSITIONS,
        current=current,
        target=target,
    )
