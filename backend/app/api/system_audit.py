"""系统级审计查询：只返回 project_id IS NULL 的记录，仅系统管理员可读。

项目级审计仍在 `app.api.audit`，两条链路互不越界。
"""

from datetime import datetime
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.responses import AuditLogData, COMMON_ERRORS, PagedEnvelope, ok_page
from app.core.errors import SystemAdminOnlyError
from app.db.session import get_db
from app.models import AuditLog, User

router = APIRouter(
    prefix="/api/v1/system/audit-logs",
    tags=["审计"],
    responses=COMMON_ERRORS,
)


@router.get("", response_model=PagedEnvelope[AuditLogData])
def list_system_audit_logs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    action: str | None = None,
    actor_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    if not user.is_system_admin:
        raise SystemAdminOnlyError("仅系统管理员可查询系统级审计")

    filters = [AuditLog.project_id.is_(None)]
    if action is not None:
        filters.append(AuditLog.action == action)
    if actor_id is not None:
        filters.append(AuditLog.actor_id == actor_id)
    if start_at is not None:
        filters.append(AuditLog.created_at >= start_at)
    if end_at is not None:
        filters.append(AuditLog.created_at <= end_at)

    total = db.scalar(select(func.count()).select_from(AuditLog).where(*filters)) or 0
    rows = db.execute(
        select(AuditLog, User.display_name)
        .outerjoin(User, User.id == AuditLog.actor_id)
        .where(*filters)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page(
        [
            {
                "id": str(row.id),
                "actor_id": str(row.actor_id) if row.actor_id else None,
                "actor_name": actor_name,
                "action": row.action,
                "target_type": row.target_type,
                "target_id": str(row.target_id) if row.target_id else None,
                "created_at": row.created_at,
            }
            for row, actor_name in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )
