"""事务性 Outbox：业务写库与事件入队在同一事务，Worker 只消费已提交事件。

两类事件，边界由库层 CHECK 与服务层共同约束：

- 项目级事件：`project_id` 必填，`payload` 必须携带一致的 `project_id`；
  topic 只能取 `ALLOWED_TOPICS`（当前只实现监测任务执行，其他 topic 不开放，
  避免生产者写入消费者不支持、只能永久 pending 的事件）。
- 系统级事件：库层 CHECK 仍允许 `system.` 前缀的 topic 不带 project_id，
  但服务层白名单 `SYSTEM_TOPICS` 当前为空——所有系统级 topic 都没有实现
  消费者，一律拒绝生产，保证“每个允许的 topic 都有消费者”的事件契约。
  未来实现消费者时，把对应 topic 加回白名单即可。
"""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import ProjectAccessError
from app.models import OutboxEvent
from app.models.enums import OutboxStatus

ALLOWED_TOPICS = frozenset({"monitoring.task.execute"})

SYSTEM_TOPIC_PREFIX = "system."
# 无消费者的系统级 topic 一律不开放：避免事件入队后无人消费、永久占用投递批次。
SYSTEM_TOPICS = frozenset()


def emit_event(
    db: Session,
    *,
    project_id: uuid.UUID,
    topic: str,
    payload: dict[str, Any],
) -> OutboxEvent:
    """项目级事件：项目键必填，payload 与事件归属必须一致。"""
    if project_id is None:
        raise ProjectAccessError("event requires project scope")
    if topic not in ALLOWED_TOPICS:
        raise ValueError(f"topic not allowed: {topic}")
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")

    # payload 必须自带项目键且与事件归属一致，Worker 消费时再校验一次
    if str(payload.get("project_id")) != str(project_id):
        raise ProjectAccessError("payload must carry matching project_id")

    event = OutboxEvent(
        project_id=project_id,
        topic=topic,
        payload=payload,
        status=OutboxStatus.PENDING,
    )
    db.add(event)
    return event


def emit_system_event(
    db: Session,
    *,
    topic: str,
    payload: dict[str, Any],
) -> OutboxEvent:
    """系统级事件：无项目归属，只允许 `system.` 前缀的白名单 topic。

    当前白名单为空（所有系统级 topic 均无消费者），一律拒绝生产；
    实现消费者后，把对应 topic 加回 `SYSTEM_TOPICS` 再开放。
    """
    if not topic.startswith(SYSTEM_TOPIC_PREFIX) or topic not in SYSTEM_TOPICS:
        raise ValueError(f"system topic not allowed: {topic}")
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")
    if payload.get("project_id") is not None:
        raise ProjectAccessError("system event must not carry project_id")

    event = OutboxEvent(
        project_id=None,
        topic=topic,
        payload=payload,
        status=OutboxStatus.PENDING,
    )
    db.add(event)
    return event
