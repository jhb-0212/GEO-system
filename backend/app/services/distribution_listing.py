"""投喂批次（Distribution）的读取口径与快照组装。

`api/distribution.py` 只留校验、事务与审计；批次自身的读法集中在这里：

- `batch_row` / `page_batches`：批次取数与分页；
- `version_titles`：创建批次时核对内容版本属于本项目；
- `batch_payload`：一次把条目、渠道名、引擎名组装成页面用的快照。
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import (
    AiEngine,
    Channel,
    ContentItem,
    ContentVersion,
    DistributionBatch,
    DistributionBatchItem,
)


def _uuids(values) -> list[uuid.UUID]:
    parsed: list[uuid.UUID] = []
    for value in values or []:
        try:
            parsed.append(uuid.UUID(str(value)))
        except ValueError:
            continue
    return parsed


def channel_names(db: Session, channel_ids) -> list[str]:
    parsed = _uuids(channel_ids)
    if not parsed:
        return []
    rows = db.execute(
        select(Channel.id, Channel.name).where(Channel.id.in_(parsed))
    ).all()
    return [row.name for row in rows]


def engine_names(db: Session, engine_ids) -> list[str]:
    parsed = _uuids(engine_ids)
    if not parsed:
        return []
    rows = db.execute(
        select(AiEngine.id, AiEngine.name).where(AiEngine.id.in_(parsed))
    ).all()
    return [row.name for row in rows]


def items_of(db: Session, batch_id: uuid.UUID) -> list[DistributionBatchItem]:
    return list(
        db.scalars(
            select(DistributionBatchItem).where(
                DistributionBatchItem.batch_id == batch_id
            )
        ).all()
    )


def version_titles(
    db: Session, project_id: uuid.UUID, version_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    rows = db.execute(
        select(ContentVersion.id, ContentItem.title)
        .join(ContentItem, ContentItem.id == ContentVersion.item_id)
        .where(
            ContentVersion.project_id == project_id,
            ContentVersion.id.in_(version_ids),
        )
    ).all()
    return {row.id: row.title for row in rows}


def batch_payload(
    db: Session,
    batch: DistributionBatch,
    items: list[DistributionBatchItem] | None = None,
) -> dict:
    items = items if items is not None else items_of(db, batch.id)
    return {
        "id": str(batch.id),
        "name": batch.name,
        "status": batch.status.value,
        "threshold_note": "预检全过才能确认投喂；确认后按内容 × 渠道生成发布任务，回执才算发出",
        "task_count": batch.task_count,
        "approval_snapshot": batch.approval_snapshot,
        "target_channel_ids": batch.target_channel_ids,
        "channel_names": channel_names(db, batch.target_channel_ids),
        "expected_engines": batch.expected_engines,
        "expected_engine_names": engine_names(db, batch.expected_engines),
        "precheck": batch.precheck,
        "notes": batch.notes,
        "item_count": batch.item_count,
        "items": [
            {"version_id": str(item.content_version_id), "title": item.title}
            for item in items
        ],
        "last_checked_at": batch.last_checked_at,
        "dispatched_at": batch.dispatched_at,
        "created_at": batch.created_at,
    }


def page_batches(
    db: Session, project_id: uuid.UUID, *, page: int, page_size: int
) -> tuple[list[DistributionBatch], int]:
    total = int(
        db.scalar(
            select(func.count()).where(DistributionBatch.project_id == project_id)
        )
        or 0
    )
    rows = db.scalars(
        select(DistributionBatch)
        .where(DistributionBatch.project_id == project_id)
        .order_by(DistributionBatch.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), total


def batch_row(
    db: Session, project_id: uuid.UUID, batch_id: uuid.UUID, *, for_update: bool = False
) -> DistributionBatch:
    stmt = select(DistributionBatch).where(
        DistributionBatch.project_id == project_id,
        DistributionBatch.id == batch_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    batch = db.scalar(stmt)
    if batch is None:
        raise AppError("批次不存在或不属于当前项目", code="batch_not_found")
    return batch
