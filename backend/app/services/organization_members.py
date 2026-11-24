"""客户级通讯录：名册本身不授予项目访问权，同步到项目才是显式动作。

`organization_members` 只回答「这个客户有谁」；项目能不能看，仍由 `project_members` 决定。
同步只加 viewer，不复制客户角色，避免客户名册自动扩权。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Project, ProjectMember, Role, User
from app.models.enums import RoleCode
from app.models.industry import OrganizationMember


def list_members(db: Session, project: Project) -> list[dict]:
    rows = db.execute(
        select(OrganizationMember, User)
        .join(User, User.id == OrganizationMember.user_id)
        .where(
            OrganizationMember.organization_id == project.organization_id,
            OrganizationMember.is_active.is_(True),
        )
        .order_by(User.username)
    )
    return [
        {
            "user_id": str(member.user_id),
            "username": user.username,
            "display_name": user.display_name,
            "role": member.role,
            "is_active": user.is_active,
            "in_project": db.scalar(
                select(ProjectMember.id).where(
                    ProjectMember.project_id == project.id,
                    ProjectMember.user_id == member.user_id,
                    ProjectMember.is_active.is_(True),
                )
            ) is not None,
        }
        for member, user in rows
    ]


def add_member(db: Session, project: Project, user_id: uuid.UUID, role: str = "member") -> dict:
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AppError("成员不存在或已停用", code="organization_member_missing")
    from app.services.organization_settings import enforce_member_quota

    enforce_member_quota(db, project.organization_id)
    existing = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == project.organization_id,
            OrganizationMember.user_id == user_id,
        )
    )
    created = 0
    if existing is None:
        existing = OrganizationMember(
            organization_id=project.organization_id, user_id=user_id, role=role, is_active=True
        )
        db.add(existing)
        created = 1
    else:
        existing.role = role
        existing.is_active = True
    db.flush()
    return {"created": created, "user_id": str(user_id), "role": existing.role}


def remove_member(db: Session, project: Project, user_id: uuid.UUID) -> dict:
    row = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == project.organization_id,
            OrganizationMember.user_id == user_id,
        )
    )
    if row is None:
        raise AppError("客户名册中没有该成员", code="organization_member_missing")
    db.delete(row)
    return {"removed": 1, "user_id": str(user_id)}


def sync_to_project(db: Session, project: Project, actor_id: uuid.UUID | None) -> dict:
    """把客户名册中尚未进项目的成员加成 viewer；只补缺，不改已有角色。"""
    viewer = db.scalar(select(Role).where(Role.code == RoleCode.VIEWER.value))
    if viewer is None:
        raise AppError("viewer 角色未初始化", code="role_missing")
    org_members = db.scalars(
        select(OrganizationMember.user_id).where(
            OrganizationMember.organization_id == project.organization_id,
            OrganizationMember.is_active.is_(True),
        )
    ).all()
    existing = {
        row.user_id: row
        for row in db.scalars(
            select(ProjectMember).where(ProjectMember.project_id == project.id)
        )
    }
    added = 0
    skipped = 0
    for user_id in org_members:
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            skipped += 1
            continue
        row = existing.get(user_id)
        if row is not None:
            if row.is_active:
                skipped += 1
                continue
            # 曾移除过的成员：同步时按 viewer 恢复读取权，不沿用旧角色。
            row.is_active = True
            row.role_id = viewer.id
            row.granted_by = actor_id
            added += 1
            continue
        db.add(
            ProjectMember(
                project_id=project.id,
                user_id=user_id,
                role_id=viewer.id,
                is_active=True,
                granted_by=actor_id,
            )
        )
        added += 1
    db.flush()
    return {"added": added, "skipped": skipped, "role_code": RoleCode.VIEWER.value}
