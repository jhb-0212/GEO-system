"""项目成员的读取、候选人与分页，从 `api/members.py` 下沉。

列表页把角色码放进联表，避免每行再查一次 Role（原来是一行一次）。
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ResourceMissingError
from app.models import ProjectMember, Role, User
from app.models.enums import RoleCode


def role_row(db: Session, code: RoleCode) -> Role:
    role = db.scalar(select(Role).where(Role.code == code))
    if role is None:
        raise ResourceMissingError("角色未初始化", code="role_missing")
    return role


def member_row(db: Session, project_id: uuid.UUID, member_id: uuid.UUID) -> ProjectMember:
    member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.id == member_id,
        )
    )
    if member is None:
        raise ResourceMissingError("成员不存在", code="member_missing")
    return member


def role_code_of(db: Session, member: ProjectMember | None) -> str | None:
    if member is None:
        return None
    role = db.get(Role, member.role_id)
    return role.code if role else None


def member_by_user(
    db: Session, project_id: uuid.UUID, user_id: uuid.UUID
) -> ProjectMember | None:
    return db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )


def page_members(
    db: Session, project_id: uuid.UUID, *, page: int, page_size: int
) -> tuple[int, list[tuple[ProjectMember, User, str | None]]]:
    total = (
        db.scalar(
            select(func.count())
            .select_from(ProjectMember)
            .where(ProjectMember.project_id == project_id)
        )
        or 0
    )
    rows = db.execute(
        select(ProjectMember, User, Role.code)
        .join(User, User.id == ProjectMember.user_id)
        .outerjoin(Role, Role.id == ProjectMember.role_id)
        .where(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return int(total), [(row[0], row[1], row[2]) for row in rows]


def member_candidates(
    db: Session, project_id: uuid.UUID, q: str = "", *, limit: int = 20
) -> list[User]:
    """可授予的候选用户：排除当前项目在职成员（已停用成员可重新授予）。"""
    existing_user_ids = select(ProjectMember.user_id).where(
        ProjectMember.project_id == project_id,
        ProjectMember.is_active.is_(True),
    )
    stmt = (
        select(User)
        .where(User.is_active.is_(True))
        .where(User.id.not_in(existing_user_ids))
    )
    term = q.strip()
    if term:
        pattern = f"%{term}%"
        stmt = stmt.where(
            or_(
                User.username.ilike(pattern),
                User.display_name.ilike(pattern),
                User.email.ilike(pattern),
            )
        )
    return list(db.scalars(stmt.order_by(User.username).limit(limit)).all())
