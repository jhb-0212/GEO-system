"""项目列表的展示用计数：渠道数、监测任务数、项目负责人、客户名称。

这些数字只用于列表卡片，不参与任何统计口径；所以刻意用「按 project_id 分组的一次
聚合」，而不是逐项目回表。

客户名称这一项修过一个跨租户读取：原来 `select(Organization.id, Organization.name)`
不带条件，把系统里所有组织的名字都读进内存再挑几个用。现在只查当前页实际出现的
组织 id —— 数量相同，但别家客户的名字不会进这一行代码的内存。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Channel, MonitoringTask, Organization, ProjectMember, Role, User
from app.models.enums import RoleCode


def project_summaries(
    db: Session, project_ids: list[uuid.UUID]
) -> tuple[dict[uuid.UUID, int], dict[uuid.UUID, int], dict[uuid.UUID, str]]:
    """返回 (渠道数, 监测任务数, 负责人显示名)，键都是 project_id。"""
    if not project_ids:
        return {}, {}, {}

    channel_counts = dict(
        db.execute(
            select(Channel.project_id, func.count(Channel.id))
            .where(Channel.project_id.in_(project_ids))
            .group_by(Channel.project_id)
        ).all()
    )
    task_counts = dict(
        db.execute(
            select(MonitoringTask.project_id, func.count(MonitoringTask.id))
            .where(MonitoringTask.project_id.in_(project_ids))
            .group_by(MonitoringTask.project_id)
        ).all()
    )
    owner_rows = db.execute(
        select(ProjectMember.project_id, User.display_name, User.username)
        .join(User, User.id == ProjectMember.user_id)
        .join(Role, Role.id == ProjectMember.role_id)
        .where(
            ProjectMember.project_id.in_(project_ids),
            ProjectMember.is_active.is_(True),
            Role.code == RoleCode.PROJECT_ADMIN,
        )
        .order_by(ProjectMember.created_at)
    ).all()
    owners: dict[uuid.UUID, str] = {}
    for project_id, display_name, username in owner_rows:
        owners.setdefault(project_id, display_name or username)
    return channel_counts, task_counts, owners


def organization_names(
    db: Session, organization_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """只取传进来的组织名称，不做全表读取。"""
    ids = [value for value in dict.fromkeys(organization_ids) if value]
    if not ids:
        return {}
    rows = db.execute(
        select(Organization.id, Organization.name).where(Organization.id.in_(ids))
    ).all()
    return {org_id: name for org_id, name in rows}
