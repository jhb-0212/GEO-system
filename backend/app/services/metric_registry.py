"""指标口径版本的读取与版本号推进，从 `api/metrics.py` 下沉。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ResourceMissingError
from app.models import MetricDefinition


def next_rule_version(db: Session, project_id: uuid.UUID, code: str) -> int:
    current = (
        db.scalar(
            select(func.max(MetricDefinition.rule_version)).where(
                MetricDefinition.project_id == project_id,
                MetricDefinition.code == code,
            )
        )
        or 0
    )
    return current + 1


def page_metrics(
    db: Session, project_id: uuid.UUID, *, page: int, page_size: int
) -> tuple[int, list[MetricDefinition]]:
    total = (
        db.scalar(
            select(func.count())
            .select_from(MetricDefinition)
            .where(MetricDefinition.project_id == project_id)
        )
        or 0
    )
    rows = db.scalars(
        select(MetricDefinition)
        .where(MetricDefinition.project_id == project_id)
        .order_by(MetricDefinition.code, MetricDefinition.rule_version.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return int(total), list(rows)


def metric_row(
    db: Session, project_id: uuid.UUID, metric_id: uuid.UUID
) -> MetricDefinition:
    metric = db.scalar(
        select(MetricDefinition).where(
            MetricDefinition.project_id == project_id,
            MetricDefinition.id == metric_id,
        )
    )
    if metric is None:
        raise ResourceMissingError("指标口径不存在", code="metric_missing")
    return metric
