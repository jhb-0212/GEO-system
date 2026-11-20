"""状态迁移的最小校验层：只定义合法边，不做持久化、不引入状态机框架。

约定：
- 同状态视为幂等，直接放行；
- 未列出的目标状态一律拒绝，抛 `TaskRejectedError`（409 task_rejected）；
- 终态没有出边，重试必须新建任务/样本 attempt，不能把旧记录改回 pending；
- 数据库 CHECK 只保证状态值合法，迁移合法性由本模块统一负责。
"""

from collections.abc import Mapping
from typing import Any

from app.core.errors import TaskRejectedError
from app.models.enums import (
    ContentStatus,
    PublishTaskStatus,
    RoundStatus,
    SampleStatus,
    TaskStatus,
)


TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
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
    ContentStatus.SCHEDULED: frozenset(
        {ContentStatus.PUBLISHED, ContentStatus.NEEDS_ATTENTION, ContentStatus.ARCHIVED}
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
        {ContentStatus.SCHEDULED, ContentStatus.PUBLISHED, ContentStatus.ARCHIVED}
    ),
    ContentStatus.ARCHIVED: frozenset(),
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
