"""竞品台账的读取、查重与引用计数，从 `api/competitors.py` 下沉。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ResourceMissingError
from app.models import Competitor, MonitoringCitation, MonitoringCompetitorMention


def competitor_payload(competitor: Competitor) -> dict:
    return {
        "id": str(competitor.id),
        "name": competitor.name,
        "domain": competitor.domain,
        "is_active": competitor.is_active,
        "notes": competitor.notes,
        "created_at": competitor.created_at,
        "updated_at": competitor.updated_at,
    }


def competitor_row(
    db: Session,
    project_id: uuid.UUID,
    competitor_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> Competitor:
    query = select(Competitor).where(
        Competitor.project_id == project_id,
        Competitor.id == competitor_id,
    )
    if for_update:
        query = query.with_for_update()
    competitor = db.scalar(query)
    if competitor is None:
        raise ResourceMissingError("竞品不存在", code="competitor_missing")
    return competitor


def name_exists(
    db: Session,
    project_id: uuid.UUID,
    name: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    stmt = select(Competitor.id).where(
        Competitor.project_id == project_id,
        Competitor.name == name,
    )
    if exclude_id is not None:
        stmt = stmt.where(Competitor.id != exclude_id)
    return db.scalar(stmt) is not None


def reference_counts(
    db: Session, project_id: uuid.UUID, competitor_id: uuid.UUID
) -> tuple[int, int]:
    """历史提及与引用关联数；有任一关联就不允许硬删，保护 SOV 历史统计。"""
    mentions = (
        db.scalar(
            select(func.count())
            .select_from(MonitoringCompetitorMention)
            .where(
                MonitoringCompetitorMention.project_id == project_id,
                MonitoringCompetitorMention.competitor_id == competitor_id,
            )
        )
        or 0
    )
    citations = (
        db.scalar(
            select(func.count())
            .select_from(MonitoringCitation)
            .where(
                MonitoringCitation.project_id == project_id,
                MonitoringCitation.competitor_id == competitor_id,
            )
        )
        or 0
    )
    return int(mentions), int(citations)


def page_competitors(
    db: Session, project_id: uuid.UUID, *, page: int, page_size: int
) -> tuple[list[Competitor], int]:
    total = (
        db.scalar(
            select(func.count())
            .select_from(Competitor)
            .where(Competitor.project_id == project_id)
        )
        or 0
    )
    rows = db.scalars(
        select(Competitor)
        .where(Competitor.project_id == project_id)
        .order_by(Competitor.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), int(total)
