"""客户级设置：成员继承、配额、客户级策略。

设置存在 `organizations.settings`，是客户自己的默认值，不是代码常量：
- `inherit_members`：新建项目时是否把名册成员加成 viewer（默认关闭，避免静默扩权）；
- `quotas`：projects / members / project_members，空值表示不限；
- `strategy`：客户级策略，合并顺序为 行业预设 → 客户策略 → 项目策略。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Project, ProjectMember, Role, User
from app.models.enums import RoleCode
from app.models.industry import Organization, OrganizationMember

DEFAULTS: dict[str, Any] = {
    "inherit_members": False,
    "quotas": {"projects": None, "members": None, "project_members": None},
    "strategy": {},
}


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def get_settings(db: Session, organization_id: uuid.UUID) -> dict:
    org = db.get(Organization, organization_id)
    if org is None:
        raise AppError("客户不存在", code="organization_missing")
    settings = _deep_merge(DEFAULTS, org.settings if isinstance(org.settings, dict) else {})
    quotas = settings.get("quotas") or {}
    return {
        "organization_id": str(org.id),
        "code": org.code,
        "name": org.name,
        "inherit_members": bool(settings.get("inherit_members")),
        "quotas": {
            "projects": quotas.get("projects"),
            "members": quotas.get("members"),
            "project_members": quotas.get("project_members"),
        },
        "strategy": settings.get("strategy") or {},
        "usage": {
            "projects": db.scalar(select(func.count(Project.id)).where(Project.organization_id == org.id)) or 0,
            "members": db.scalar(
                select(func.count(OrganizationMember.id)).where(
                    OrganizationMember.organization_id == org.id,
                    OrganizationMember.is_active.is_(True),
                )
            ) or 0,
        },
    }


def _clean_quota(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AppError(f"配额 {field} 必须是非负整数或 null", code="organization_quota_invalid")
    return value


def update_settings(db: Session, organization_id: uuid.UUID, payload: dict) -> dict:
    org = db.get(Organization, organization_id)
    if org is None:
        raise AppError("客户不存在", code="organization_missing")
    current = _deep_merge(DEFAULTS, org.settings if isinstance(org.settings, dict) else {})

    if "inherit_members" in payload:
        if not isinstance(payload["inherit_members"], bool):
            raise AppError("inherit_members 必须是布尔值", code="organization_settings_invalid")
        current["inherit_members"] = payload["inherit_members"]

    if "quotas" in payload:
        quotas = payload["quotas"] or {}
        if not isinstance(quotas, dict):
            raise AppError("quotas 必须是对象", code="organization_settings_invalid")
        merged = dict(current.get("quotas") or {})
        for key in ("projects", "members", "project_members"):
            if key in quotas:
                merged[key] = _clean_quota(quotas[key], key)
        current["quotas"] = merged

    if "strategy" in payload:
        strategy = payload["strategy"] or {}
        if not isinstance(strategy, dict):
            raise AppError("strategy 必须是对象", code="organization_settings_invalid")
        current["strategy"] = strategy

    org.settings = current
    db.flush()
    return get_settings(db, organization_id)


def enforce_project_quota(db: Session, organization_id: uuid.UUID) -> None:
    limits = get_settings(db, organization_id)["quotas"]
    limit = limits.get("projects")
    if limit is None:
        return
    used = db.scalar(select(func.count(Project.id)).where(Project.organization_id == organization_id)) or 0
    if used >= limit:
        raise AppError(
            f"客户项目配额已用完（{used}/{limit}）", code="organization_project_quota_exceeded"
        )


def enforce_member_quota(db: Session, organization_id: uuid.UUID) -> None:
    limits = get_settings(db, organization_id)["quotas"]
    limit = limits.get("members")
    if limit is None:
        return
    used = db.scalar(
        select(func.count(OrganizationMember.id)).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.is_active.is_(True),
        )
    ) or 0
    if used >= limit:
        raise AppError(
            f"客户成员配额已用完（{used}/{limit}）", code="organization_member_quota_exceeded"
        )


def enforce_project_member_quota(db: Session, project: Project) -> None:
    limits = get_settings(db, project.organization_id)["quotas"]
    limit = limits.get("project_members")
    if limit is None:
        return
    used = db.scalar(
        select(func.count(ProjectMember.id)).where(
            ProjectMember.project_id == project.id, ProjectMember.is_active.is_(True)
        )
    ) or 0
    if used >= limit:
        raise AppError(
            f"项目成员配额已用完（{used}/{limit}）", code="organization_project_member_quota_exceeded"
        )


def inherit_members(db: Session, project: Project, owner_id: uuid.UUID) -> dict:
    """按客户设置把名册成员加成 viewer；只补缺、不覆盖角色，超出项目成员配额就停。"""
    settings = get_settings(db, project.organization_id)
    if not settings["inherit_members"]:
        return {"enabled": False, "added": 0, "skipped": 0}
    viewer = db.scalar(select(Role).where(Role.code == RoleCode.VIEWER.value))
    if viewer is None:
        raise AppError("viewer 角色未初始化", code="role_missing")
    existing = {
        row.user_id
        for row in db.scalars(
            select(ProjectMember).where(ProjectMember.project_id == project.id)
        )
    }
    limit = settings["quotas"].get("project_members")
    added = 0
    skipped = 0
    for user_id in db.scalars(
        select(OrganizationMember.user_id).where(
            OrganizationMember.organization_id == project.organization_id,
            OrganizationMember.is_active.is_(True),
        )
    ).all():
        if user_id == owner_id or user_id in existing:
            skipped += 1
            continue
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            skipped += 1
            continue
        if limit is not None and len(existing) >= limit:
            skipped += 1
            continue
        db.add(
            ProjectMember(
                project_id=project.id,
                user_id=user_id,
                role_id=viewer.id,
                is_active=True,
                granted_by=owner_id,
            )
        )
        existing.add(user_id)
        added += 1
    db.flush()
    return {"enabled": True, "added": added, "skipped": skipped}
