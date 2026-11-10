"""事务性 Outbox：业务写库与事件入队在同一事务，Worker 只消费已提交事件。

强制约束：每个事件必须带 project_id（库内 NOT NULL），payload 里的 project_id 也必须一致，
否则异步链路会出现跨项目数据串用。

边界：outbox 只承载**项目级**异步事件。系统级变更（建项目、引擎目录维护、权限矩阵调整）
没有项目归属，不走 outbox，只写 audit_logs；他们不需要异步执行，也不该出现在 Worker 队列。
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


def emit_event(
    db: Session,
    *,
    project_id: uuid.UUID,
    topic: str,
    payload: dict[str, Any],
) -> OutboxEvent:
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
