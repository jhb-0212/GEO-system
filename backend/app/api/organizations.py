"""客户主体（organizations）：列、建、改名。

客户是项目之上的一层边界：配额、名册、继承与客户策略都挂在它上面。
这里只做主体管理，不代替项目成员的授权。
"""

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_system_permission
from app.api.responses import COMMON_ERRORS, Envelope, ok
from app.core.errors import AppError
from app.db.session import get_db
from app.models import Project, User
from app.models.industry import Organization, OrganizationMember

router = APIRouter(prefix="/api/v1/organizations", tags=["客户"], responses=COMMON_ERRORS)


class OrganizationCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=128)


class OrganizationRename(BaseModel):
    name: str = Field(min_length=1, max_length=128)


def _serialize(org: Organization, project_count: int = 0, member_count: int = 0) -> dict:
    return {
        "id": str(org.id),
        "code": org.code,
        "name": org.name,
        "status": org.status,
        "project_count": project_count,
        "member_count": member_count,
    }


@router.get("", response_model=Envelope[list[dict]])
def list_organizations(
    q: str | None = Query(default=None, max_length=64, description="按编码/名称模糊搜索"),
    user: User = Depends(require_system_permission("project.create")),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Organization).order_by(Organization.code)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Organization.code.ilike(like) | Organization.name.ilike(like))
    rows = db.scalars(stmt).all()
    project_counts = dict(
        db.execute(select(Project.organization_id, func.count(Project.id)).group_by(Project.organization_id)).all()
    )
    member_counts = dict(
        db.execute(
            select(OrganizationMember.organization_id, func.count(OrganizationMember.id)).where(
                OrganizationMember.is_active.is_(True)
            ).group_by(OrganizationMember.organization_id)
        ).all()
    )
    return ok([
        _serialize(row, project_counts.get(row.id, 0), member_counts.get(row.id, 0))
        for row in rows
    ])


@router.post("", status_code=201, response_model=Envelope[dict])
def create_organization(
    payload: OrganizationCreate,
    user: User = Depends(require_system_permission("project.create")),
    db: Session = Depends(get_db),
) -> dict:
    code = payload.code.strip().lower()
    if db.scalar(select(Organization).where(Organization.code == code)) is not None:
        raise AppError("客户编码已存在", code="organization_code_exists")
    org = Organization(code=code, name=payload.name.strip(), status="active")
    db.add(org)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise AppError("客户编码已存在", code="organization_code_exists") from exc
    db.commit()
    return ok(_serialize(org))


@router.patch("/{organization_id}", response_model=Envelope[dict])
def rename_organization(
    organization_id: uuid.UUID,
    payload: OrganizationRename,
    user: User = Depends(require_system_permission("project.create")),
    db: Session = Depends(get_db),
) -> dict:
    org = db.get(Organization, organization_id)
    if org is None:
        raise AppError("客户不存在", code="organization_missing")
    org.name = payload.name.strip()
    db.commit()
    return ok(_serialize(org))
