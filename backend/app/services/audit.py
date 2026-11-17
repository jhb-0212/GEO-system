"""审计留痕：导出、删除、权限变更、审批、发布必须写 audit_logs，不允许静默操作。"""

import uuid
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ExportTooLargeError
from app.models import AuditLog

_BUSINESS_WRITE_FLAG = "_audit_business_write_pending"


@event.listens_for(Session, "before_flush")
def _mark_business_write(session: Session, flush_context, instances) -> None:
    """记录本事务是否发生过非审计写入。

    一旦业务对象被 flush，`session.new/dirty/deleted` 会被清空；只在 `record_denial`
    里检查这三个集合会漏掉已 flush 的业务写入。这里在每次 flush 前打标，
    `after_commit` / `after_rollback` 再清掉，保证拒绝审计不会代提交半成品业务数据。
    """
    if any(not isinstance(obj, AuditLog) for obj in session.new):
        session.info[_BUSINESS_WRITE_FLAG] = True
    if session.dirty or session.deleted:
        session.info[_BUSINESS_WRITE_FLAG] = True


@event.listens_for(Session, "after_commit")
def _clear_business_write_after_commit(session: Session) -> None:
    session.info.pop(_BUSINESS_WRITE_FLAG, None)


@event.listens_for(Session, "after_rollback")
def _clear_business_write_after_rollback(session: Session) -> None:
    session.info.pop(_BUSINESS_WRITE_FLAG, None)


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
    """越权拒绝审计：拒绝必须留痕，但不能替调用方提交半成品的业务写入。

    只有当前事务里除审计外没有其他待提交对象时才 commit；一旦发现业务写入还挂着
    （包括已 flush、已不在 `session.new/dirty/deleted` 里的写入），只把审计放进同一事务
    （宁可本次审计随请求回滚，也不能把未完成的业务数据提前落库）。
    调用点通常都在权限判定阶段、尚未发生业务写入，因此正常路径仍能独立留痕。
    """
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
    pending_business = [
        obj
        for obj in (*db.new, *db.dirty, *db.deleted)
        if not isinstance(obj, AuditLog)
    ]
    if not pending_business and not db.info.get(_BUSINESS_WRITE_FLAG):
        db.commit()
    return row
