"""Project-scoped audit log read API for the workbench activity view."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import AuditLogData, COMMON_ERRORS, PagedEnvelope, ok_page
from app.db.session import get_db
from app.models import AuditLog, User

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/audit-logs",
    tags=["审计"],
    responses=COMMON_ERRORS,
)


@router.get("", response_model=PagedEnvelope[AuditLogData])
def list_audit_logs(
    ctx: ProjectContext = Depends(require_permission("audit.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    project_id: uuid.UUID = ctx.project.id
    total = db.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.project_id == project_id)
    ) or 0
    rows = db.execute(
        select(AuditLog, User.display_name)
        .outerjoin(User, User.id == AuditLog.actor_id)
        .where(AuditLog.project_id == project_id)
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
