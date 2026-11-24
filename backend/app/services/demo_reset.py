"""演练项目监测数据重置：只清监测证据链，保留题目/品牌/竞品/客户配置。"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    MonitoringCitation,
    MonitoringCompetitorMention,
    MonitoringExecutionAttempt,
    MonitoringRetestPlan,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    OutboxEvent,
    SentimentLabel,
    StatSnapshot,
)


def reset_project_monitoring(
    db: Session,
    project_id: uuid.UUID,
    *,
    drop_retest_plans: bool = False,
    dry_run: bool = False,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    steps = [
        ("competitor_mentions", MonitoringCompetitorMention),
        ("sentiment_labels", SentimentLabel),
        ("citations", MonitoringCitation),
        ("samples", MonitoringSample),
        ("attempts", MonitoringExecutionAttempt),
        ("tasks", MonitoringTask),
        ("snapshots", StatSnapshot),
        ("rounds", MonitoringRound),
    ]
    for label, model in steps:
        if dry_run:
            counts[label] = int(
                db.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.project_id == project_id)
                )
                or 0
            )
            continue
        result = db.execute(delete(model).where(model.project_id == project_id))
        counts[label] = int(result.rowcount or 0)
    if dry_run:
        counts["outbox_events"] = int(
            db.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(
                    OutboxEvent.project_id == project_id,
                    OutboxEvent.topic == "monitoring.task.execute",
                )
            )
            or 0
        )
    else:
        result = db.execute(
            delete(OutboxEvent).where(
                OutboxEvent.project_id == project_id,
                OutboxEvent.topic == "monitoring.task.execute",
            )
        )
        counts["outbox_events"] = int(result.rowcount or 0)
    if drop_retest_plans:
        if dry_run:
            counts["retest_plans"] = int(
                db.scalar(
                    select(func.count())
                    .select_from(MonitoringRetestPlan)
                    .where(MonitoringRetestPlan.project_id == project_id)
                )
                or 0
            )
        else:
            result = db.execute(
                delete(MonitoringRetestPlan).where(MonitoringRetestPlan.project_id == project_id)
            )
            counts["retest_plans"] = int(result.rowcount or 0)
    if not dry_run:
        db.flush()
    return counts
