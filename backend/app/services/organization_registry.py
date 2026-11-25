"""客户主体（organizations）的读取与计数聚合，从 `api/organizations.py` 下沉。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Project, ProjectMember
from app.models.industry import Organization, OrganizationMember


def organization_payload(org: Organization, project_count: int = 0, member_count: int = 0) -> dict:
    return {
        "id": str(org.id),
        "code": org.code,
        "name": org.name,
        "status": org.status,
        "branding": org.branding or {},
        "project_count": project_count,
        "member_count": member_count,
    }


def all_organizations(db: Session, q: str | None = None) -> list[Organization]:
    stmt = select(Organization).order_by(Organization.code)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Organization.code.ilike(like) | Organization.name.ilike(like))
    return list(db.scalars(stmt).all())


def organization_by_code(db: Session, code: str) -> Organization | None:
    return db.scalar(select(Organization).where(Organization.code == code))


def organization_row(db: Session, organization_id: uuid.UUID) -> Organization:
    org = db.get(Organization, organization_id)
    if org is None:
        raise AppError("客户不存在", code="organization_missing")
    return org


def project_counts(db: Session) -> dict:
    return dict(
        db.execute(
            select(Project.organization_id, func.count(Project.id)).group_by(
                Project.organization_id
            )
        ).all()
    )


def active_member_counts(db: Session) -> dict:
    return dict(
        db.execute(
            select(OrganizationMember.organization_id, func.count(OrganizationMember.id))
            .where(OrganizationMember.is_active.is_(True))
            .group_by(OrganizationMember.organization_id)
        ).all()
    )


def max_project_members(db: Session) -> dict:
    """每个客户名下「单个项目最多成员数」，成员配额是项目粒度的。"""
    per_project = db.execute(
        select(Project.organization_id, func.count(ProjectMember.id))
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.is_active.is_(True))
        .group_by(Project.organization_id, Project.id)
    ).all()
    result: dict = {}
    for org_id, count in per_project:
        result[org_id] = max(result.get(org_id, 0), count)
    return result
