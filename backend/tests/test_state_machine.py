"""状态迁移表的最小单测：只验证合法边、终态和错误码，不依赖数据库。"""

import pytest

from app.core.errors import TaskRejectedError
from app.models.enums import (
    PublishTaskStatus,
    RoundStatus,
    SampleStatus,
    TaskStatus,
)
from app.services.state_machine import (
    ensure_publish_transition,
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
