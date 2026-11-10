"""事务性 Outbox：业务写库与事件入队在同一事务，Worker 只消费已提交事件。

两类事件，边界由库层 CHECK 与服务层共同约束：

- 项目级事件：`project_id` 必填，`payload` 必须携带一致的 `project_id`；
  topic 只能取 `ALLOWED_TOPICS`（监测、发布、导出、审批、证据采集）。
- 系统级事件：`project_id` 为空，topic 必须以 `system.` 开头（如 `system.engine.catalog.sync`）；
  库层 `ck_outbox_events_project_or_system` 保证系统事件不会被 NOT NULL 卡住，
  同时禁止项目级 topic 伪装成无项目事件。
"""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import ProjectAccessError
from app.models import OutboxEvent
from app.models.enums import OutboxStatus

ALLOWED_TOPICS = frozenset(
    {
        "monitoring.task.execute",
        "publish.task.execute",
        "export.task.run",
        "content.review.request",
        "evidence.collect",
    }
)

SYSTEM_TOPIC_PREFIX = "system."
SYSTEM_TOPICS = frozenset(
    {
        "system.engine.catalog.sync",
        "system.permission.matrix.sync",
    }
)


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
    """系统级事件：无项目归属，只允许 `system.` 前缀的白名单 topic。"""
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
