"""状态迁移表的最小单测：只验证合法边、终态和错误码，不依赖数据库。"""

import pytest

from app.core.errors import ConflictError, TaskRejectedError
from app.models.enums import (
    BudgetApprovalStatus,
    ChannelStatus,
    CorrectionTaskStatus,
    OpportunityStatus,
    PublishTaskStatus,
    QuestionStatus,
    RoundStatus,
    SampleStatus,
    TaskStatus,
)
from app.services.state_machine import (
    ensure_budget_approval_transition,
    ensure_channel_transition,
    ensure_correction_task_transition,
    ensure_opportunity_transition,
    ensure_publish_transition,
    ensure_question_transition,
    ensure_round_transition,
    ensure_sample_transition,
    ensure_task_transition,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskStatus.PENDING, TaskStatus.RUNNING),
        (TaskStatus.PENDING, TaskStatus.CANCELLED),
        (TaskStatus.RUNNING, TaskStatus.DONE),
        (TaskStatus.RUNNING, TaskStatus.FAILED),
        (TaskStatus.RUNNING, TaskStatus.CANCELLED),
        (TaskStatus.UNCERTAIN, TaskStatus.DONE),
        (TaskStatus.FAILED, TaskStatus.DONE),
    ],
)
def test_task_allowed_transitions(current, target):
    assert ensure_task_transition(current, target) == target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskStatus.PENDING, TaskStatus.DONE),
        (TaskStatus.DONE, TaskStatus.RUNNING),
        (TaskStatus.FAILED, TaskStatus.PENDING),
        (TaskStatus.CANCELLED, TaskStatus.RUNNING),
    ],
)
def test_task_rejects_invalid_transitions(current, target):
    with pytest.raises(TaskRejectedError) as exc:
        ensure_task_transition(current, target)
    assert exc.value.status_code == 409
    assert exc.value.code == "task_rejected"


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (SampleStatus.PENDING, SampleStatus.RUNNING),
        (SampleStatus.PENDING, SampleStatus.FAILED),
        (SampleStatus.RUNNING, SampleStatus.HIT),
        (SampleStatus.RUNNING, SampleStatus.MISS),
        (SampleStatus.RUNNING, SampleStatus.MANUAL_REVIEW),
        (SampleStatus.MANUAL_REVIEW, SampleStatus.HIT),
        (SampleStatus.MANUAL_REVIEW, SampleStatus.MISS),
    ],
)
def test_sample_allowed_transitions(current, target):
    assert ensure_sample_transition(current, target) == target


def test_sample_rejects_terminal_or_shortcut():
    with pytest.raises(TaskRejectedError):
        ensure_sample_transition(SampleStatus.PENDING, SampleStatus.HIT)
    with pytest.raises(TaskRejectedError):
        ensure_sample_transition(SampleStatus.HIT, SampleStatus.RUNNING)
    with pytest.raises(TaskRejectedError):
        ensure_sample_transition(SampleStatus.FAILED, SampleStatus.PENDING)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (RoundStatus.PLANNING, RoundStatus.RUNNING),
        (RoundStatus.PLANNING, RoundStatus.CLOSED),
        (RoundStatus.RUNNING, RoundStatus.COMPLETED),
        (RoundStatus.RUNNING, RoundStatus.CLOSED),
        (RoundStatus.COMPLETED, RoundStatus.CLOSED),
    ],
)
def test_round_allowed_transitions(current, target):
    assert ensure_round_transition(current, target) == target


def test_round_rejects_closed_reopen():
    with pytest.raises(TaskRejectedError):
        ensure_round_transition(RoundStatus.CLOSED, RoundStatus.RUNNING)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (PublishTaskStatus.PENDING, PublishTaskStatus.PUBLISHING),
        (PublishTaskStatus.PENDING, PublishTaskStatus.FAILED),
        (PublishTaskStatus.PENDING, PublishTaskStatus.NEEDS_REVIEW),
        (PublishTaskStatus.NEEDS_REVIEW, PublishTaskStatus.PUBLISHING),
        (PublishTaskStatus.PUBLISHING, PublishTaskStatus.PUBLISHED),
        (PublishTaskStatus.PUBLISHING, PublishTaskStatus.UNKNOWN),
        (PublishTaskStatus.PUBLISHING, PublishTaskStatus.FAILED),
    ],
)
def test_publish_allowed_transitions(current, target):
    assert ensure_publish_transition(current, target) == target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (PublishTaskStatus.UNKNOWN, PublishTaskStatus.FAILED),
        (PublishTaskStatus.PUBLISHING, PublishTaskStatus.PUBLISHING),
        (PublishTaskStatus.PUBLISHED, PublishTaskStatus.PUBLISHING),
        (PublishTaskStatus.FAILED, PublishTaskStatus.PENDING),
    ],
)
def test_publish_rejects_unknown_or_terminal(current, target):
    with pytest.raises(TaskRejectedError):
        ensure_publish_transition(current, target)


def test_same_state_is_idempotent():
    assert ensure_task_transition(TaskStatus.DONE, TaskStatus.DONE) == TaskStatus.DONE
    assert ensure_sample_transition(SampleStatus.HIT, SampleStatus.HIT) == SampleStatus.HIT


# --- 题目：草稿→启用→归档，归档可复活；draft 不能直跳 archived（沿用既有错误码） ---


def test_question_transitions():
    assert (
        ensure_question_transition(QuestionStatus.DRAFT, QuestionStatus.ACTIVE)
        == QuestionStatus.ACTIVE
    )
    assert (
        ensure_question_transition(QuestionStatus.ACTIVE, QuestionStatus.ARCHIVED)
        == QuestionStatus.ARCHIVED
    )
    assert (
        ensure_question_transition(QuestionStatus.ARCHIVED, QuestionStatus.ACTIVE)
        == QuestionStatus.ACTIVE
    )
    with pytest.raises(ConflictError) as exc:
        ensure_question_transition(QuestionStatus.DRAFT, QuestionStatus.ARCHIVED)
    # 前端按这个码判断冲突，不能换成 task_rejected
    assert exc.value.code == "question_status_conflict"


# --- 预算审批：通过/驳回都是终态，不能改判 ---


def test_budget_approval_transitions():
    for target in (BudgetApprovalStatus.APPROVED, BudgetApprovalStatus.REJECTED):
        assert (
            ensure_budget_approval_transition(BudgetApprovalStatus.PENDING, target) == target
        )
    with pytest.raises(TaskRejectedError):
        ensure_budget_approval_transition(
            BudgetApprovalStatus.APPROVED, BudgetApprovalStatus.REJECTED
        )
    with pytest.raises(TaskRejectedError):
        ensure_budget_approval_transition(
            BudgetApprovalStatus.REJECTED, BudgetApprovalStatus.APPROVED
        )


# --- 纠错任务：允许回退与重开，但不允许从 OPEN 直接 RESOLVED ---


def test_correction_task_transitions():
    assert (
        ensure_correction_task_transition(
            CorrectionTaskStatus.OPEN, CorrectionTaskStatus.IN_PROGRESS
        )
        == CorrectionTaskStatus.IN_PROGRESS
    )
    assert (
        ensure_correction_task_transition(
            CorrectionTaskStatus.OPEN, CorrectionTaskStatus.DISMISSED
        )
        == CorrectionTaskStatus.DISMISSED
    )
    assert (
        ensure_correction_task_transition(
            CorrectionTaskStatus.IN_PROGRESS, CorrectionTaskStatus.RESOLVED
        )
        == CorrectionTaskStatus.RESOLVED
    )
    # 已解决发现结论错了可以重开
    assert (
        ensure_correction_task_transition(
            CorrectionTaskStatus.RESOLVED, CorrectionTaskStatus.IN_PROGRESS
        )
        == CorrectionTaskStatus.IN_PROGRESS
    )
    with pytest.raises(TaskRejectedError):
        ensure_correction_task_transition(
            CorrectionTaskStatus.OPEN, CorrectionTaskStatus.RESOLVED
        )


# --- 机会：完成/放弃都可重开 ---


def test_opportunity_transitions():
    assert (
        ensure_opportunity_transition(OpportunityStatus.OPEN, OpportunityStatus.DONE)
        == OpportunityStatus.DONE
    )
    assert (
        ensure_opportunity_transition(OpportunityStatus.DONE, OpportunityStatus.IN_PROGRESS)
        == OpportunityStatus.IN_PROGRESS
    )
    assert (
        ensure_opportunity_transition(OpportunityStatus.DISMISSED, OpportunityStatus.OPEN)
        == OpportunityStatus.OPEN
    )
    assert (
        ensure_opportunity_transition(
            OpportunityStatus.OPEN, OpportunityStatus.DISMISSED
        )
        == OpportunityStatus.DISMISSED
    )


# --- 渠道台账：published 是终态，不许降级回 observed ---


def test_channel_allowed_transitions():
    assert (
        ensure_channel_transition(ChannelStatus.CANDIDATE, ChannelStatus.OBSERVED)
        == ChannelStatus.OBSERVED
    )
    assert (
        ensure_channel_transition(ChannelStatus.CANDIDATE, ChannelStatus.PUBLISHED)
        == ChannelStatus.PUBLISHED
    )
    assert (
        ensure_channel_transition(
            ChannelStatus.REVIEW_PENDING, ChannelStatus.PUBLISHED
        )
        == ChannelStatus.PUBLISHED
    )
    assert (
        ensure_channel_transition(ChannelStatus.OBSERVED, ChannelStatus.PUBLISHED)
        == ChannelStatus.PUBLISHED
    )


def test_channel_rejects_downgrade_from_published():
    with pytest.raises(TaskRejectedError):
        ensure_channel_transition(ChannelStatus.PUBLISHED, ChannelStatus.OBSERVED)
