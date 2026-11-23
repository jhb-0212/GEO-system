"""投喂批次：创建时即跑预检，预检不过 blocked；只有 ready 才能标记已投喂。"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, PagedEnvelope, ok_page, ok
from app.core.errors import AppError
from app.db.session import get_db
from app.models import AiEngine, ContentItem, ContentVersion, DistributionBatch, DistributionBatchItem, User
from app.models.enums import DistributionBatchStatus
from app.services.audit import record_audit
from app.services.distribution import run_precheck

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/distribution-batches",
    tags=["投喂批次"],
    responses=COMMON_ERRORS,
)


class BatchIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    content_version_ids: list[uuid.UUID] = Field(default_factory=list)
    engine_ids: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=2000)


def _serialize(batch: DistributionBatch, items: list[DistributionBatchItem], engine_names: list[str]) -> dict:
    return {
        "id": str(batch.id),
        "name": batch.name,
        "status": batch.status.value,
        "threshold_note": "预检全过才可标记已投喂",
        "target_engines": batch.target_engines,
        "engine_names": engine_names,
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


def _engine_names(db: Session, engine_ids: list[str]) -> list[str]:
    parsed = []
    for engine_id in engine_ids:
        try:
            parsed.append(uuid.UUID(str(engine_id)))
        except ValueError:
            continue
    if not parsed:
        return []
    rows = db.execute(select(AiEngine.id, AiEngine.name).where(AiEngine.id.in_(parsed))).all()
    return [row.name for row in rows]


def _items_of(db: Session, batch_id: uuid.UUID) -> list[DistributionBatchItem]:
    return list(db.scalars(select(DistributionBatchItem).where(DistributionBatchItem.batch_id == batch_id)).all())


def _check_and_save(db: Session, batch: DistributionBatch, version_ids: list[uuid.UUID], project_id: uuid.UUID) -> None:
    precheck = run_precheck(db, project_id, version_ids=version_ids, engine_ids=list(batch.target_engines or []))
    batch.precheck = precheck
    batch.last_checked_at = datetime.now(timezone.utc)
    if batch.status != DistributionBatchStatus.DISPATCHED:
        batch.status = DistributionBatchStatus(precheck["status"])


@router.get("", response_model=PagedEnvelope[dict])
def list_batches(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    total = int(db.scalar(select(func.count()).where(DistributionBatch.project_id == ctx.project.id)) or 0)
    rows = db.scalars(
        select(DistributionBatch)
        .where(DistributionBatch.project_id == ctx.project.id)
        .order_by(DistributionBatch.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page(
        [
            _serialize(batch, _items_of(db, batch.id), _engine_names(db, list(batch.target_engines or [])))
            for batch in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", status_code=201, response_model=Envelope[dict])
def create_batch(
    payload: BatchIn,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    if not payload.content_version_ids:
        raise AppError("投喂批次至少要选一个内容版本", code="batch_empty")
    if not payload.engine_ids:
        raise AppError("投喂批次至少要选一个目标平台", code="batch_no_engine")

    versions = db.execute(
        select(ContentVersion.id, ContentItem.title)
        .join(ContentItem, ContentItem.id == ContentVersion.item_id)
        .where(
            ContentVersion.project_id == ctx.project.id,
            ContentVersion.id.in_(payload.content_version_ids),
        )
    ).all()
    titles = {row.id: row.title for row in versions}
    missing = [version_id for version_id in payload.content_version_ids if version_id not in titles]
    if missing:
        raise AppError("选中的内容版本不属于当前项目", code="batch_version_not_found")

    batch = DistributionBatch(
        project_id=ctx.project.id,
        name=payload.name.strip(),
        target_engines=[str(engine_id) for engine_id in payload.engine_ids],
        notes=payload.notes,
        item_count=len(payload.content_version_ids),
        created_by=ctx.user.id,
    )
    db.add(batch)
    db.flush()

    for version_id in payload.content_version_ids:
        db.add(
            DistributionBatchItem(
                batch_id=batch.id,
                content_version_id=version_id,
                title=titles[version_id],
            )
        )

    _check_and_save(db, batch, payload.content_version_ids, ctx.project.id)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="distribution.create",
        target_type="distribution_batch",
        target_id=batch.id,
        payload={"item_count": batch.item_count, "status": batch.status.value},
    )
    db.commit()
    db.refresh(batch)
    return ok(_serialize(batch, _items_of(db, batch.id), _engine_names(db, list(batch.target_engines or []))))


@router.get("/{batch_id}", response_model=Envelope[dict])
def get_batch(
    batch_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
):
    batch = db.scalar(
        select(DistributionBatch).where(
            DistributionBatch.project_id == ctx.project.id,
            DistributionBatch.id == batch_id,
        )
    )
    if batch is None:
        raise AppError("批次不存在或不属于当前项目", code="batch_not_found")
    items = _items_of(db, batch.id)
    return ok(_serialize(batch, items, _engine_names(db, list(batch.target_engines or []))))


@router.post("/{batch_id}/recheck", response_model=Envelope[dict])
def recheck_batch(
    batch_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
):
    batch = db.scalar(
        select(DistributionBatch).where(
            DistributionBatch.project_id == ctx.project.id,
            DistributionBatch.id == batch_id,
        )
    )
    if batch is None:
        raise AppError("批次不存在或不属于当前项目", code="batch_not_found")
    items = _items_of(db, batch.id)
    _check_and_save(db, batch, [item.content_version_id for item in items], ctx.project.id)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="distribution.recheck",
        target_type="distribution_batch",
        target_id=batch.id,
        payload={"status": batch.status.value},
    )
    db.commit()
    return ok(_serialize(batch, items, _engine_names(db, list(batch.target_engines or []))))


@router.post("/{batch_id}/dispatch", response_model=Envelope[dict])
def dispatch_batch(
    batch_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
):
    """标记已投喂：必须先预检通过，且允许先重检一次再判定。"""
    batch = db.scalar(
        select(DistributionBatch).where(
            DistributionBatch.project_id == ctx.project.id,
            DistributionBatch.id == batch_id,
        )
    )
    if batch is None:
        raise AppError("批次不存在或不属于当前项目", code="batch_not_found")
    if batch.status == DistributionBatchStatus.DISPATCHED:
        raise AppError("该批次已标记为已投喂", code="batch_already_dispatched")

    items = _items_of(db, batch.id)
    precheck = run_precheck(
        db, ctx.project.id,
        version_ids=[item.content_version_id for item in items],
        engine_ids=list(batch.target_engines or []),
    )
    batch.precheck = precheck
    batch.last_checked_at = datetime.now(timezone.utc)
    if not precheck["ready"]:
        batch.status = DistributionBatchStatus.BLOCKED
        db.commit()
        raise AppError(
            f"预检未通过（{len(precheck['failed'])} 项），先补齐再投喂",
            code="batch_precheck_failed",
        )

    batch.status = DistributionBatchStatus.DISPATCHED
    batch.dispatched_at = datetime.now(timezone.utc)
    batch.dispatched_by = ctx.user.id
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="distribution.dispatch",
        target_type="distribution_batch",
        target_id=batch.id,
        payload={"item_count": batch.item_count},
    )
    db.commit()
    return ok(_serialize(batch, items, _engine_names(db, list(batch.target_engines or []))))
