"""Outbox 消费者：只投递已提交事件，成功才把事件标 dispatched。

不在 API 请求里发 Celery：API 与事件同事务落库，由独立的 dispatcher 进程消费；
这样消息发送失败不会丢业务事件，事件也不会在事务回滚后仍被投递。

失败治理：单条投递失败保留 pending 并累计 `failure_count`，达到配置上限后
置 FAILED（死信），不再占用后续投递批次——避免永久失败的事件按创建时间
排在队首、阻塞后面所有正常事件。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import OutboxEvent
from app.models.enums import OutboxStatus

logger = logging.getLogger(__name__)


def dispatch_pending_events(
    db: Session,
    send_event: Callable[[OutboxEvent], None],
    *,
    limit: int = 50,
) -> dict[str, int]:
    """取 pending 事件并逐条投递；失败保留 pending 并计数，达上限置死信。"""
    events = db.scalars(
        select(OutboxEvent)
        .where(OutboxEvent.status == OutboxStatus.PENDING)
        .order_by(OutboxEvent.created_at, OutboxEvent.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()

    dispatched = 0
    failed = 0
    dead = 0
    for event in events:
        try:
            send_event(event)
        except Exception as exc:
            failed += 1
            event.failure_count = (event.failure_count or 0) + 1
            event.error_note = (str(exc) or type(exc).__name__)[:2000]
            if event.failure_count >= settings.outbox_max_failures:
                event.status = OutboxStatus.FAILED
                event.dispatched_at = datetime.now(timezone.utc)
                dead += 1
            logger.warning(
                "outbox dispatch failed",
                extra={
                    "fields": {
                        "event_id": str(event.id),
                        "topic": event.topic,
                        "failure_count": event.failure_count,
                        "dead_lettered": event.status == OutboxStatus.FAILED,
                    }
                },
            )
            continue
        event.status = OutboxStatus.DISPATCHED
        event.dispatched_at = datetime.now(timezone.utc)
        dispatched += 1
    db.flush()
    return {
        "pending_count": len(events),
        "dispatched_count": dispatched,
        "failed_count": failed,
        "dead_letter_count": dead,
    }
