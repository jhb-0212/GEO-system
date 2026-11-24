"""客户级设置：成员继承、配额、客户级策略。

设置存在 `organizations.settings`，是客户自己的默认值，不是代码常量：
- `inherit_members`：新建项目时是否把名册成员加成 viewer（默认关闭，避免静默扩权）；
- `quotas`：projects / members / project_members，空值表示不限；
- `strategy`：客户级策略，合并顺序为 行业预设 → 客户策略 → 项目策略。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Project, ProjectMember, Role, User
from app.models.industry import Organization, OrganizationMember, OrganizationUsageSnapshot

DEFAULTS: dict[str, Any] = {
    "inherit_members": False,
    # 继承到项目的默认角色；只允许只读/编辑/审核，项目管理员必须显式授予。
    "inherit_role": "viewer",
    "quotas": {"projects": None, "members": None, "project_members": None},
    "strategy": {},
}

INHERIT_ROLES = ("viewer", "editor", "reviewer")


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


_QUOTA_LABELS = {"projects": "客户项目数", "members": "客户名册人数", "project_members": "单项目成员数"}


def _alert(key: str, used: int, limit: int | None) -> dict | None:
    label = _QUOTA_LABELS.get(key, key)
    if limit is None:
        return None
    if used >= limit:
        return {"key": key, "used": used, "limit": limit, "level": "exceeded", "message": f"{label} 已达上限 {used}/{limit}"}
    if limit > 0 and used * 5 >= limit * 4:
        return {"key": key, "used": used, "limit": limit, "level": "warning", "message": f"{label} 已用 {used}/{limit}，接近上限"}
    return None


def get_settings(db: Session, organization_id: uuid.UUID, project_id: uuid.UUID | None = None) -> dict:
    org = db.get(Organization, organization_id)
    if org is None:
        raise AppError("客户不存在", code="organization_missing")
    settings = _deep_merge(DEFAULTS, org.settings if isinstance(org.settings, dict) else {})
    quotas = settings.get("quotas") or {}
    used_projects = db.scalar(select(func.count(Project.id)).where(Project.organization_id == org.id)) or 0
    used_members = db.scalar(
        select(func.count(OrganizationMember.id)).where(
            OrganizationMember.organization_id == org.id,
            OrganizationMember.is_active.is_(True),
        )
    ) or 0
    used_project_members = 0
    if project_id is not None:
        used_project_members = db.scalar(
            select(func.count(ProjectMember.id)).where(
                ProjectMember.project_id == project_id, ProjectMember.is_active.is_(True)
            )
        ) or 0
    return {
        "organization_id": str(org.id),
        "code": org.code,
        "name": org.name,
        "inherit_members": bool(settings.get("inherit_members")),
        "inherit_role": settings.get("inherit_role") or "viewer",
        "quotas": {
            "projects": quotas.get("projects"),
            "members": quotas.get("members"),
            "project_members": quotas.get("project_members"),
        },
        "strategy": settings.get("strategy") or {},
        "usage": {
            "projects": used_projects,
            "members": used_members,
            "project_members": used_project_members,
        },
        "alerts": [
            alert for alert in (
                _alert("projects", used_projects, quotas.get("projects")),
                _alert("members", used_members, quotas.get("members")),
                _alert("project_members", used_project_members, quotas.get("project_members")),
            ) if alert is not None
        ],
    }


def _clean_quota(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AppError(f"配额 {field} 必须是非负整数或 null", code="organization_quota_invalid")
    return value


def _current_usage(db: Session, organization_id: uuid.UUID) -> tuple[int, int]:
    projects = db.scalar(select(func.count(Project.id)).where(Project.organization_id == organization_id)) or 0
    members = db.scalar(
        select(func.count(OrganizationMember.id)).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.is_active.is_(True),
        )
    ) or 0
    return int(projects), int(members)


def capture_usage_snapshots(db: Session, *, on_date: Any = None) -> dict:
    """给所有启用客户写当天快照；重复执行按当天覆盖，不追加多行。"""
    day = on_date or datetime.now(UTC).date()
    written = 0
    for org_id in db.scalars(select(Organization.id)).all():
        projects, members = _current_usage(db, org_id)
        row = db.scalar(
            select(OrganizationUsageSnapshot).where(
                OrganizationUsageSnapshot.organization_id == org_id,
                OrganizationUsageSnapshot.captured_on == day,
            )
        )
        if row is None:
            db.add(
                OrganizationUsageSnapshot(
                    organization_id=org_id, captured_on=day, projects=projects, members=members
                )
            )
        else:
            row.projects = projects
            row.members = members
        written += 1
    db.flush()
    return {"date": day.isoformat(), "organizations": written}


def usage_trend(db: Session, organization_id: uuid.UUID, days: int = 30) -> dict:
    """近 N 天用量：当天写快照，历史优先读快照，缺失日期用创建时间回算并在点上标注。"""
    days = max(1, min(days, 90))
    today = datetime.now(UTC).date()
    start = today - timedelta(days=days - 1)
    capture_usage_snapshots(db, on_date=today)

    snapshot_rows = db.scalars(
        select(OrganizationUsageSnapshot)
        .where(
            OrganizationUsageSnapshot.organization_id == organization_id,
            OrganizationUsageSnapshot.captured_on >= start,
            OrganizationUsageSnapshot.captured_on <= today,
        )
        .order_by(OrganizationUsageSnapshot.captured_on)
    ).all()
    snapshots = {row.captured_on: row for row in snapshot_rows}

    project_rows = db.scalars(
        select(Project.created_at).where(Project.organization_id == organization_id)
    ).all()
    member_rows = db.scalars(
        select(OrganizationMember.created_at).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.is_active.is_(True),
        )
    ).all()

    def _bucket(rows) -> dict:
        counts: dict[Any, int] = {}
        for created_at in rows:
            date = created_at.date()
            if date >= start:
                counts[date] = counts.get(date, 0) + 1
        return counts

    project_counts = _bucket(project_rows)
    member_counts = _bucket(member_rows)
    base_projects = sum(1 for created_at in project_rows if created_at.date() < start)
    base_members = sum(1 for created_at in member_rows if created_at.date() < start)
    series = []
    for offset in range(days):
        date = start + timedelta(days=offset)
        base_projects += project_counts.get(date, 0)
        base_members += member_counts.get(date, 0)
        snapshot = snapshots.get(date)
        if snapshot is not None:
            projects, members, source = snapshot.projects, snapshot.members, "snapshot"
        else:
            projects, members, source = base_projects, base_members, "recalculated"
        series.append(
            {
                "date": date.isoformat(),
                "projects": projects,
                "members": members,
                "source": source,
            }
        )
    return {
        "days": days,
        "series": series,
        "snapshot_days": len(snapshots),
        "recalculated_days": days - len(snapshots),
    }


def update_settings(db: Session, organization_id: uuid.UUID, payload: dict) -> dict:
    org = db.get(Organization, organization_id)
    if org is None:
        raise AppError("客户不存在", code="organization_missing")
    current = _deep_merge(DEFAULTS, org.settings if isinstance(org.settings, dict) else {})

    if "inherit_members" in payload:
        if not isinstance(payload["inherit_members"], bool):
            raise AppError("inherit_members 必须是布尔值", code="organization_settings_invalid")
        current["inherit_members"] = payload["inherit_members"]

    if "inherit_role" in payload:
        role = str(payload["inherit_role"] or "viewer")
        if role not in INHERIT_ROLES:
            raise AppError(
                f"inherit_role 只能是 {', '.join(INHERIT_ROLES)}", code="organization_settings_invalid"
            )
        current["inherit_role"] = role

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
    """按客户设置把名册成员加进项目；只补缺、不覆盖角色，超出项目成员配额就停。"""
    settings = get_settings(db, project.organization_id)
    if not settings["inherit_members"]:
        return {"enabled": False, "added": 0, "skipped": 0, "role_code": None}
    role_code = settings.get("inherit_role") or "viewer"
    role = db.scalar(select(Role).where(Role.code == role_code))
    if role is None:
        raise AppError(f"{role_code} 角色未初始化", code="role_missing")
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
                role_id=role.id,
                is_active=True,
                granted_by=owner_id,
            )
        )
        existing.add(user_id)
        added += 1
    db.flush()
    return {"enabled": True, "added": added, "skipped": skipped}
