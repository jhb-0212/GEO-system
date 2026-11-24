"""审计日志分页（项目级与系统级共用），从 `api/audit.py` / `api/system_audit.py` 下沉。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, User


def audit_page(
    db: Session,
    filters: list,
    *,
    page: int,
    page_size: int,
) -> tuple[int, list[tuple[AuditLog, str | None]]]:
    total = db.scalar(select(func.count()).select_from(AuditLog).where(*filters)) or 0
    rows = db.execute(
        select(AuditLog, User.display_name)
        .outerjoin(User, User.id == AuditLog.actor_id)
        .where(*filters)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return int(total), [(row[0], row[1]) for row in rows]


def project_audit_page(
    db: Session, project_id: uuid.UUID, *, page: int, page_size: int
) -> tuple[int, list[tuple[AuditLog, str | None]]]:
    return audit_page(
        db, [AuditLog.project_id == project_id], page=page, page_size=page_size
    )
