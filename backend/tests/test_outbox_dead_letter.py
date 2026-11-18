"""Outbox 死信治理：永久失败事件不阻塞投递批次。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import OutboxEvent
from app.models.enums import OutboxStatus
from app.services.outbox import emit_event
from app.services.outbox_dispatch import dispatch_pending_events


def _always_fail(event: OutboxEvent) -> None:
    raise ValueError("no handler for this event")


def _ok(event: OutboxEvent) -> None:
    return None


def test_failed_event_counts_up_and_becomes_dead_letter(db, two_projects):
    p1, _ = two_projects
    event = emit_event(
        db,
        project_id=p1.id,
        topic="monitoring.task.execute",
        payload={"project_id": str(p1.id), "task_id": str(uuid.uuid4())},
    )
    db.commit()

    for i in range(1, settings.outbox_max_failures + 1):
        stats = dispatch_pending_events(db, _always_fail, limit=50)
        assert stats["failed_count"] == 1
        assert stats["dispatched_count"] == 0
        db.commit()
        refreshed = db.get(OutboxEvent, event.id)
        assert refreshed is not None
        assert refreshed.failure_count == i
        if i < settings.outbox_max_failures:
            assert refreshed.status == OutboxStatus.PENDING
        else:
            assert refreshed.status == OutboxStatus.FAILED
            assert refreshed.error_note == "no handler for this event"

    # 死信不再进入投递批次：后续轮次 pending 为 0，永久失败不再占位。
    stats = dispatch_pending_events(db, _always_fail, limit=50)
    assert stats == {
        "pending_count": 0,
        "dispatched_count": 0,
        "failed_count": 0,
        "dead_letter_count": 0,
    }


def test_dead_letter_does_not_block_newer_events(db, two_projects):
    """队首永久失败事件进死信后，排在后面的正常事件可以被消费。"""
    p1, _ = two_projects

    dead = emit_event(
        db,
        project_id=p1.id,
        topic="monitoring.task.execute",
        payload={"project_id": str(p1.id), "task_id": str(uuid.uuid4())},
    )
    # 制造一条更早的、已到死信门槛的事件排在最前。
    dead.failure_count = settings.outbox_max_failures
    dead.status = OutboxStatus.FAILED
    dead.created_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.flush()

    fresh = emit_event(
        db,
        project_id=p1.id,
        topic="monitoring.task.execute",
        payload={"project_id": str(p1.id), "task_id": str(uuid.uuid4())},
    )
    db.commit()

    stats = dispatch_pending_events(db, _ok, limit=50)
    db.commit()
    assert stats["dispatched_count"] == 1
    assert stats["pending_count"] == 1  # 只取到 pending 的 fresh，死信不在批次
    refreshed = db.get(OutboxEvent, fresh.id)
    assert refreshed is not None
    assert refreshed.status == OutboxStatus.DISPATCHED
    assert refreshed.dispatched_at is not None
    dead_refreshed = db.get(OutboxEvent, dead.id)
    assert dead_refreshed is not None
    assert dead_refreshed.status == OutboxStatus.FAILED
    assert dead_refreshed.dispatched_at is None


def test_unknown_topic_event_never_blocks_batch(db, two_projects):
    """消费者不支持的事件（如历史遗留 system topic）达到上限后进死信，不阻塞批次。"""
    p1, _ = two_projects
    # 直插一条历史遗留 system 事件：库层 CHECK 允许，但没有消费者。
    from sqlalchemy import text

    db.execute(
        text(
            "insert into outbox_events (id, project_id, topic, payload, status, created_at) "
            "values (gen_random_uuid(), null, 'system.engine.catalog.sync', '{}'::jsonb, 'pending', now())"
        )
    )
    event = emit_event(
        db,
        project_id=p1.id,
        topic="monitoring.task.execute",
        payload={"project_id": str(p1.id), "task_id": str(uuid.uuid4())},
    )
    db.commit()

    # system 事件在队首，前 N-1 轮都失败但不影响后面的 monitoring 事件被投递：
    # 同一轮里先失败（计数+1），正常事件仍继续投递。
    stats = dispatch_pending_events(db, lambda e: _ok(e) if e.project_id is not None else _always_fail(e), limit=50)
    db.commit()
    assert stats["failed_count"] == 1
    assert stats["dispatched_count"] == 1
    refreshed = db.get(OutboxEvent, event.id)
    assert refreshed is not None
    assert refreshed.status == OutboxStatus.DISPATCHED
