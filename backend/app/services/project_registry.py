"""项目级读取与查重，从 `api/projects.py` 下沉。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import IndustryPreset, Project, ProjectMember, Role, User
from app.models.enums import RoleCode


def page_projects(
    db: Session,
    user: User,
    *,
    page: int,
    page_size: int,
    organization_id: uuid.UUID | None = None,
) -> tuple[int, list[Project]]:
    """系统管理员看全部项目；其他人只看自己已加入的项目。"""
    if user.is_system_admin:
        stmt = select(Project)
    else:
        stmt = (
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user.id, ProjectMember.is_active.is_(True))
        )
    if organization_id is not None:
        stmt = stmt.where(Project.organization_id == organization_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Project.code).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return int(total), list(rows)


def code_exists(db: Session, code: str) -> bool:
    return db.scalar(select(Project.id).where(Project.code == code)) is not None


def project_admin_role(db: Session) -> Role | None:
    return db.scalar(select(Role).where(Role.code == RoleCode.PROJECT_ADMIN))


def industry_presets(db: Session) -> list[IndustryPreset]:
    return list(db.scalars(select(IndustryPreset).order_by(IndustryPreset.code)).all())


def user_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))
