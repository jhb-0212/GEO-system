"""Outbox 与审计测试：事件必须带项目键，导出必须留痕且受行数上限约束。"""

import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.errors import ExportTooLargeError, ProjectAccessError
from app.models import AuditLog, OutboxEvent
from app.services.audit import record_export, record_permission_change
from app.services.outbox import emit_event


def test_event_requires_project_key(db, two_projects, user_factory):
    p1, _ = two_projects
    user = user_factory(f"evt-{uuid.uuid4().hex[:8]}")

    with pytest.raises(ProjectAccessError):
        emit_event(db, project_id=p1.id, topic="monitoring.task.execute", payload={"task_id": "x"})

    with pytest.raises(ProjectAccessError):
        emit_event(
            db,
            project_id=p1.id,
            topic="monitoring.task.execute",
            payload={"project_id": str(uuid.uuid4())},
        )

    with pytest.raises(ValueError):
        emit_event(db, project_id=p1.id, topic="unknown.topic", payload={"project_id": str(p1.id)})

    event = emit_event(
        db,
        project_id=p1.id,
        topic="monitoring.task.execute",
        payload={"project_id": str(p1.id), "task_id": str(uuid.uuid4())},
    )
    db.flush()
    assert event.project_id == p1.id
    assert event.status.value == "pending"


def test_export_audit_written_and_limited(db, two_projects, user_factory):
    p1, _ = two_projects
    user = user_factory(f"exp-{uuid.uuid4().hex[:8]}")

    row = record_export(
        db,
        project_id=p1.id,
        actor_id=user.id,
        export_type="channels",
        row_count=10,
        filters={"category": "video"},
    )
    db.flush()
    assert row.action == "export"
    assert row.payload["row_count"] == 10
    assert row.payload["mode"] == "sync"

    with pytest.raises(ExportTooLargeError):
        record_export(
            db,
            project_id=p1.id,
            actor_id=user.id,
            export_type="channels",
            row_count=settings.export_sync_row_limit + 1,
        )


def test_permission_change_is_audited(db, two_projects, user_factory):
    p1, _ = two_projects
    admin = user_factory(f"adm-{uuid.uuid4().hex[:8]}")
    member_id = uuid.uuid4()
    row = record_permission_change(
        db, project_id=p1.id, actor_id=admin.id, member_id=member_id, before="viewer", after="editor"
    )
    db.flush()
    assert row.action == "permission_change"
    assert row.payload == {"before": "viewer", "after": "editor"}

    stored = db.scalar(select(AuditLog).where(AuditLog.id == row.id))
    assert stored is not None
    assert stored.project_id == p1.id
