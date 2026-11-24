"""状态迁移表的最小单测：只验证合法边、终态和错误码，不依赖数据库。"""

import re
from enum import StrEnum

import pytest

import app.models.enums as enums_module
import app.services.state_machine as state_machine

from app.core.errors import ConflictError, TaskRejectedError
from app.models.enums import (
    BudgetApprovalStatus,
    CitationReviewStatus,
    ChannelApprovalStatus,
    ChannelStatus,
    CorrectionTaskStatus,
    EnrollmentStatus,
    FactStatus,
    MetricStatus,
    OpportunityStatus,
    PagePublishStatus,
    PublishTaskStatus,
    QuestionStatus,
    RoundStatus,
    SampleStatus,
    TaskStatus,
)
from app.services.state_machine import (
    ensure_budget_approval_transition,
    ensure_channel_approval_transition,
    ensure_channel_transition,
    ensure_citation_review_transition,
    ensure_correction_task_transition,
    ensure_enrollment_transition,
    ensure_fact_transition,
    ensure_metric_transition,
    ensure_page_publish_transition,
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


# --- 后续批次：事实 / 页面 / 指标 / 线索 / 引用复核 / 渠道准入 ---


def test_fact_transitions():
    assert (
        ensure_fact_transition(FactStatus.DRAFT, FactStatus.PENDING_REVIEW)
        == FactStatus.PENDING_REVIEW
    )
    assert (
        ensure_fact_transition(FactStatus.PENDING_REVIEW, FactStatus.APPROVED)
        == FactStatus.APPROVED
    )
    assert (
        ensure_fact_transition(FactStatus.PENDING_REVIEW, FactStatus.DRAFT)
        == FactStatus.DRAFT
    )
    assert (
        ensure_fact_transition(FactStatus.APPROVED, FactStatus.EXPIRED)
        == FactStatus.EXPIRED
    )
    with pytest.raises(TaskRejectedError):
        ensure_fact_transition(FactStatus.EXPIRED, FactStatus.APPROVED)


def test_page_publish_transitions():
    assert (
        ensure_page_publish_transition(
            PagePublishStatus.DRAFT, PagePublishStatus.PUBLISHED
        )
        == PagePublishStatus.PUBLISHED
    )
    assert (
        ensure_page_publish_transition(
            PagePublishStatus.PUBLISHED, PagePublishStatus.OFFLINE
        )
        == PagePublishStatus.OFFLINE
    )
    assert (
        ensure_page_publish_transition(
            PagePublishStatus.OFFLINE, PagePublishStatus.PUBLISHED
        )
        == PagePublishStatus.PUBLISHED
    )


def test_metric_transitions():
    assert (
        ensure_metric_transition(MetricStatus.ACTIVE, MetricStatus.RETIRED)
        == MetricStatus.RETIRED
    )
    assert (
        ensure_metric_transition(MetricStatus.RETIRED, MetricStatus.ACTIVE)
        == MetricStatus.ACTIVE
    )


def test_enrollment_transitions():
    assert (
        ensure_enrollment_transition(
            EnrollmentStatus.UNKNOWN, EnrollmentStatus.CONTACTED
        )
        == EnrollmentStatus.CONTACTED
    )
    assert (
        ensure_enrollment_transition(
            EnrollmentStatus.ENROLLED, EnrollmentStatus.LOST
        )
        == EnrollmentStatus.LOST
    )
    assert (
        ensure_enrollment_transition(EnrollmentStatus.LOST, EnrollmentStatus.CONTACTED)
        == EnrollmentStatus.CONTACTED
    )


def test_citation_review_transitions_reject_auto_writeback():
    assert (
        ensure_citation_review_transition(
            CitationReviewStatus.AUTO, CitationReviewStatus.MANUAL_CONFIRMED
        )
        == CitationReviewStatus.MANUAL_CONFIRMED
    )
    assert (
        ensure_citation_review_transition(
            CitationReviewStatus.MANUAL_CONFIRMED, CitationReviewStatus.MANUAL_REJECTED
        )
        == CitationReviewStatus.MANUAL_REJECTED
    )
    with pytest.raises(TaskRejectedError):
        ensure_citation_review_transition(
            CitationReviewStatus.MANUAL_CONFIRMED, CitationReviewStatus.AUTO
        )


def test_channel_approval_transitions():
    assert (
        ensure_channel_approval_transition(
            ChannelApprovalStatus.PENDING_REVIEW, ChannelApprovalStatus.APPROVED
        )
        == ChannelApprovalStatus.APPROVED
    )
    assert (
        ensure_channel_approval_transition(
            ChannelApprovalStatus.PENDING_REVIEW, ChannelApprovalStatus.REJECTED
        )
        == ChannelApprovalStatus.REJECTED
    )
    assert (
        ensure_channel_approval_transition(
            ChannelApprovalStatus.REJECTED, ChannelApprovalStatus.PENDING_REVIEW
        )
        == ChannelApprovalStatus.PENDING_REVIEW
    )
    with pytest.raises(TaskRejectedError):
        ensure_channel_approval_transition(
            ChannelApprovalStatus.APPROVED, ChannelApprovalStatus.PENDING_REVIEW
        )


# --- 结构闸门：每个状态枚举都要么有迁移表，要么明确登记为「无写入方」 ---

STATUS_ENUM_EXEMPTIONS = {
    # 值 = (理由, 允许的初始写入点)；初始写入点只允许「建对象时定初值」，出现第二处就该建表
    "ProjectStatus": (
        "项目只有建项目时落 ACTIVE，没有停用/归档动作",
        {"api/projects.py"},
    ),
    "ContentPlanStatus": ("内容计划状态全仓只有字段默认值 proposed", set()),
    "ImportBatchStatus": ("导入批次状态全仓只有字段默认值 pending", set()),
    "HealthCheckStatus": ("体检结论按单项结果聚合，状态枚举只用于统计判定", set()),
}


def test_every_status_enum_has_transition_table():
    missing = []
    for name, obj in vars(enums_module).items():
        if not (name.endswith("Status") and isinstance(obj, type)):
            continue
        if not issubclass(obj, StrEnum):
            continue
        table = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name[: -len("Status")]).upper()
        if not hasattr(state_machine, f"{table}_TRANSITIONS") and name not in STATUS_ENUM_EXEMPTIONS:
            missing.append(name)
    assert not missing, f"以下状态枚举既没有迁移表也没有登记豁免：{missing}"


def test_status_enum_exemptions_still_have_no_write_sites():
    """豁免名单是「没有代码写它」的声明，将来出现写入方就必须建表，这条会失败。"""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = []
    # 只看 api / services：models 与 schemas 里的是建表默认值，不是迁移
    scan = list((root / "api").rglob("*.py")) + list((root / "services").rglob("*.py"))
    for name, (_reason, allowed) in STATUS_ENUM_EXEMPTIONS.items():
        # 只认「写字段」的两种形态：`obj.xxx = X` 与 `values(xxx=X)`
        # 单纯的 `status=ProjectStatus.X` 是查询条件（如 fetch_one 的过滤 kwargs），不算写入方
        assign = re.compile(rf"\.\w+\s*=\s*{name}\.|values\([^)]*{name}\.")
        for path in scan:
            rel = path.relative_to(root).as_posix()
            if rel in allowed:
                continue
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if "default" in line:
                    continue
                if assign.search(line):
                    offenders.append(f"{name}@{rel}:{lineno}")
    assert not offenders, offenders
