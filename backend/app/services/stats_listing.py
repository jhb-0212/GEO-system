"""统计快照 / 月报快照 / 任务分布 的读取，从 `api/stats.py` 下沉。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ResourceMissingError
from app.models import (
    AiEngine,
    AiEngineEntry,
    Channel,
    ContentPlan,
    MonitoringTask,
    MonthlyReportSnapshot,
    StatSnapshot,
    User,
)


def stat_snapshots(
    db: Session, project_id: uuid.UUID, round_id: uuid.UUID | None = None
) -> list[StatSnapshot]:
    conditions = [StatSnapshot.project_id == project_id]
    if round_id is not None:
        conditions.append(StatSnapshot.round_id == round_id)
    return list(
        db.scalars(
            select(StatSnapshot)
            .where(*conditions)
            .order_by(StatSnapshot.captured_at.desc())
        ).all()
    )


def stat_snapshot_row(
    db: Session, project_id: uuid.UUID, snapshot_id: uuid.UUID
) -> StatSnapshot:
    row = db.scalar(
        select(StatSnapshot).where(
            StatSnapshot.project_id == project_id,
            StatSnapshot.id == snapshot_id,
        )
    )
    if row is None:
        raise ResourceMissingError("统计快照不存在")
    return row


def monthly_snapshots(
    db: Session,
    project_id: uuid.UUID,
    *,
    month: str | None,
    limit: int,
) -> list[tuple[MonthlyReportSnapshot, str | None]]:
    conditions = [MonthlyReportSnapshot.project_id == project_id]
    if month is not None:
        conditions.append(MonthlyReportSnapshot.month == month)
    rows = db.execute(
        select(MonthlyReportSnapshot, User.display_name)
        .outerjoin(User, User.id == MonthlyReportSnapshot.captured_by)
        .where(*conditions)
        .order_by(
            MonthlyReportSnapshot.month.desc(),
            MonthlyReportSnapshot.captured_at.desc(),
        )
        .limit(limit)
    ).all()
    return [(row[0], row[1]) for row in rows]


def monthly_snapshot_row(
    db: Session, project_id: uuid.UUID, snapshot_id: uuid.UUID
) -> tuple[MonthlyReportSnapshot, str | None]:
    row = db.scalar(
        select(MonthlyReportSnapshot).where(
            MonthlyReportSnapshot.project_id == project_id,
            MonthlyReportSnapshot.id == snapshot_id,
        )
    )
    if row is None:
        raise ResourceMissingError("月报快照不存在")
    captured_by_name = (
        db.scalar(select(User.display_name).where(User.id == row.captured_by))
        if row.captured_by
        else None
    )
    return row, captured_by_name


def report_plans(
    db: Session, project_id: uuid.UUID
) -> list[tuple[ContentPlan, str | None, str | None]]:
    """月报 Markdown 里的计划清单：计划 + 负责人用户名 + 渠道名。"""
    rows = db.execute(
        select(ContentPlan, User.username, Channel.name)
        .outerjoin(User, User.id == ContentPlan.owner_id)
        .outerjoin(Channel, Channel.id == ContentPlan.channel_id)
        .where(ContentPlan.project_id == project_id)
        .order_by(ContentPlan.plan_type, ContentPlan.status, ContentPlan.scheduled_at)
    ).all()
    return [(row[0], row[1], row[2]) for row in rows]


def engine_task_shares(
    db: Session, project_id: uuid.UUID, round_id: uuid.UUID | None = None
) -> list[tuple[uuid.UUID, str, int]]:
    filters = [MonitoringTask.project_id == project_id]
    if round_id is not None:
        filters.append(MonitoringTask.round_id == round_id)
    rows = db.execute(
        select(AiEngine.id, AiEngine.name, func.count(MonitoringTask.id))
        .join(AiEngineEntry, AiEngineEntry.engine_id == AiEngine.id)
        .join(MonitoringTask, MonitoringTask.engine_entry_id == AiEngineEntry.id)
        .where(*filters)
        .group_by(AiEngine.id, AiEngine.name)
        .order_by(AiEngine.name)
    ).all()
    return [(row[0], row[1], int(row[2])) for row in rows]
