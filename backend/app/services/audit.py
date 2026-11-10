"""审计留痕：导出、删除、权限变更、审批、发布必须写 audit_logs，不允许静默操作。"""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ExportTooLargeError
from app.models import AuditLog


def record_audit(
    db: Session,
    *,
    project_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    action: str,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditLog:
    """写入审计记录但不提交：与业务写入同一事务，保证要么都成功要么都不留痕。"""
    row = AuditLog(
        project_id=project_id,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        payload=payload,
    )
    db.add(row)
    return row


def record_permission_change(
    db: Session,
    *,
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    member_id: uuid.UUID,
    before: str | None,
    after: str | None,
) -> AuditLog:
    return record_audit(
        db,
        project_id=project_id,
        actor_id=actor_id,
        action="permission_change",
        target_type="project_member",
        target_id=member_id,
        payload={"before": before, "after": after},
    )


def record_export(
    db: Session,
    *,
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    export_type: str,
    row_count: int,
    filters: dict[str, Any] | None = None,
    mode: str = "sync",
) -> AuditLog:
    """导出审计：同步导出受行数上限约束，超限必须转异步，且两种方式都留痕。"""
    if mode == "sync" and row_count > settings.export_sync_row_limit:
        raise ExportTooLargeError(
            f"sync export exceeds {settings.export_sync_row_limit} rows, use async export"
        )
    return record_audit(
        db,
        project_id=project_id,
        actor_id=actor_id,
        action="export",
        target_type=export_type,
        payload={"row_count": row_count, "mode": mode, "filters": filters or {}},
    )


def record_denial(
    db: Session,
    *,
    project_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    permission: str | None = None,
    role: str | None = None,
    reason: str = "permission_denied",
    path: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    """越权拒绝审计：拒绝必须留痕，所以这里单独提交，不随请求事务回滚。"""
    payload: dict[str, Any] = {"reason": reason}
    if permission:
        payload["permission"] = permission
    if role:
        payload["role"] = role
    if path:
        payload["path"] = path
    if detail:
        payload.update(detail)
    row = record_audit(
        db,
        project_id=project_id,
        actor_id=actor_id,
        action="permission_denied",
        target_type="permission",
        payload=payload,
    )
    db.commit()
    return row
