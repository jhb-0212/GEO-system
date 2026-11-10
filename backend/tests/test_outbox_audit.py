"""Outbox 与审计测试：事件必须带项目键，导出必须留痕且受行数上限约束。"""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.errors import ExportTooLargeError, ProjectAccessError
from app.models import AuditLog, OutboxEvent
from app.services.audit import record_export, record_permission_change
from app.services.outbox import emit_event, emit_system_event


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


def test_system_event_has_no_project(db):
    """系统级事件（引擎目录、权限矩阵）无项目归属，入队不能因 NOT NULL 被卡住。"""
    event = emit_system_event(
        db,
        topic="system.engine.catalog.sync",
        payload={"engine_code": "chatgpt", "reason": "目录核验"},
    )
    db.flush()
    assert event.project_id is None
    assert event.topic == "system.engine.catalog.sync"

    # 项目级 topic 不能伪装成系统事件
    with pytest.raises(ValueError):
        emit_system_event(db, topic="monitoring.task.execute", payload={})
    # 系统级 topic 不允许携带项目键
    with pytest.raises(ProjectAccessError):
        emit_system_event(
            db,
            topic="system.engine.catalog.sync",
            payload={"project_id": str(uuid.uuid4())},
        )


def test_db_check_blocks_project_topic_without_project(engine):
    """库层 CHECK：没有 project_id 的事件，topic 必须是 system.*。"""
    with engine.connect() as conn:
        try:
            conn.execute(
                text(
                    "insert into outbox_events (id, project_id, topic, payload, status, created_at) "
                    "values (gen_random_uuid(), null, 'monitoring.task.execute', '{}'::jsonb, 'pending', now())"
                )
            )
            conn.rollback()
            raise AssertionError("数据库接受了无项目归属的项目级事件，CHECK 未生效")
        except IntegrityError:
            conn.rollback()

        # system.* 事件可以没有项目归属
        conn.execute(
            text(
                "insert into outbox_events (id, project_id, topic, payload, status, created_at) "
                "values (gen_random_uuid(), null, 'system.permission.matrix.sync', '{}'::jsonb, 'pending', now())"
            )
        )
        conn.rollback()


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
