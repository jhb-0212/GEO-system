"""AI 平台目录与入口的读取/查重/引用计数，从 `api/engines.py` 下沉。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ResourceMissingError
from app.models import AiEngine, AiEngineEntry, MonitoringTask
from app.models.enums import EngineEntryType


def engine_row(db: Session, engine_id: uuid.UUID) -> AiEngine:
    engine = db.get(AiEngine, engine_id)
    if engine is None:
        raise ResourceMissingError("AI 平台不存在", code="engine_missing")
    return engine


def entry_row(db: Session, engine_id: uuid.UUID, entry_id: uuid.UUID) -> AiEngineEntry:
    entry = db.scalar(
        select(AiEngineEntry).where(
            AiEngineEntry.engine_id == engine_id,
            AiEngineEntry.id == entry_id,
        )
    )
    if entry is None:
        raise ResourceMissingError("入口不存在", code="engine_entry_missing")
    return entry


def engine_by_code(db: Session, code: str) -> AiEngine | None:
    return db.scalar(select(AiEngine).where(AiEngine.code == code))


def entry_exists(
    db: Session,
    engine_id: uuid.UUID,
    entry_type: EngineEntryType,
    name: str,
) -> bool:
    return (
        db.scalar(
            select(AiEngineEntry.id).where(
                AiEngineEntry.engine_id == engine_id,
                AiEngineEntry.entry_type == entry_type,
                AiEngineEntry.name == name,
            )
        )
        is not None
    )


def entry_task_count(db: Session, entry_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(MonitoringTask)
            .where(MonitoringTask.engine_entry_id == entry_id)
        )
        or 0
    )


def page_engines(db: Session, *, page: int, page_size: int) -> tuple[list[AiEngine], int]:
    total = db.scalar(select(func.count()).select_from(AiEngine)) or 0
    rows = db.scalars(
        select(AiEngine)
        .order_by(AiEngine.code)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), int(total)


def page_entries(
    db: Session, engine_id: uuid.UUID, *, page: int, page_size: int
) -> tuple[list[AiEngineEntry], int]:
    stmt = select(AiEngineEntry).where(AiEngineEntry.engine_id == engine_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(AiEngineEntry.created_at, AiEngineEntry.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), int(total)
