"""投喂批次：创建时即跑预检，预检不过 blocked；只有 ready 才能确认投喂。

确认投喂（dispatch）的语义是「计划已确认、任务已入队」，不是「已发出」：
它会按「内容版本 × 目标渠道」生成发布任务（`services/distribution_dispatch.py`），
回执与收录仍走发布侧链路。权限也随之从 `content.write` 改为 `publish.execute`——
对外宣称「投喂了」这件事必须由执行岗背书，编辑岗不能单方面制造这个事实。
"""

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, PagedEnvelope, ok_page, ok
from app.core.errors import AppError
from app.db.session import get_db
from app.models import AiEngine, Channel, ContentItem, ContentVersion, DistributionBatch, DistributionBatchItem, User
from app.models.enums import DistributionBatchStatus
from app.services.audit import record_audit
from app.services.distribution import apply_precheck, run_precheck
from app.services.distribution_dispatch import apply_plan

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/distribution-batches",
    tags=["投喂批次"],
    responses=COMMON_ERRORS,
)


class BatchIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    content_version_ids: list[uuid.UUID] = Field(default_factory=list)
    # 目标是渠道；引擎是「期望被引」，不是目标，不参与阻断
    channel_ids: list[uuid.UUID] = Field(default_factory=list)
    expected_engine_ids: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=2000)


def _serialize(
    batch: DistributionBatch,
    items: list[DistributionBatchItem],
    channel_names: list[str],
    engine_names: list[str],
) -> dict:
    return {
        "id": str(batch.id),
        "name": batch.name,
        "status": batch.status.value,
        "threshold_note": "预检全过才能确认投喂；确认后按内容 × 渠道生成发布任务，回执才算发出",
        "task_count": batch.task_count,
        "approval_snapshot": batch.approval_snapshot,
        "target_channel_ids": batch.target_channel_ids,
        "channel_names": channel_names,
        "expected_engines": batch.expected_engines,
        "expected_engine_names": engine_names,
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


def _channel_names(db: Session, channel_ids: list[str]) -> list[str]:
    parsed = []
    for channel_id in channel_ids:
        try:
            parsed.append(uuid.UUID(str(channel_id)))
        except ValueError:
            continue
    if not parsed:
        return []
    rows = db.execute(select(Channel.id, Channel.name).where(Channel.id.in_(parsed))).all()
    return [row.name for row in rows]


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


def _check_and_save(db: Session, batch: DistributionBatch, version_ids: list[uuid.UUID], project_id: uuid.UUID) -> dict:
    """预检重算的唯一入口：状态回写放在 service，api 不直接给 batch.status 赋值。"""
    return apply_precheck(
        db, batch, version_ids=version_ids, project_id=project_id,
        expected_engine_ids=list(batch.expected_engines or []),
    )


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
            _serialize(
                batch,
                _items_of(db, batch.id),
                _channel_names(db, list(batch.target_channel_ids or [])),
                _engine_names(db, list(batch.expected_engines or [])),
            )
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
    if not payload.channel_ids:
        raise AppError("投喂批次至少要选一个目标渠道", code="batch_no_channel")

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
        target_channel_ids=[str(channel_id) for channel_id in payload.channel_ids],
        expected_engines=[str(engine_id) for engine_id in payload.expected_engine_ids],
        notes=payload.notes,
        item_count=len(payload.content_version_ids),
        created_by=ctx.user.id,
    )
    db.add(batch)
    db.flush()

    for version_id in payload.content_version_ids:
        db.add(
            DistributionBatchItem(
                project_id=ctx.project.id,
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
    return ok(
        _serialize(
            batch,
            _items_of(db, batch.id),
            _channel_names(db, list(batch.target_channel_ids or [])),
            _engine_names(db, list(batch.expected_engines or [])),
        )
    )


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
    return ok(
        _serialize(
            batch,
            items,
            _channel_names(db, list(batch.target_channel_ids or [])),
            _engine_names(db, list(batch.expected_engines or [])),
        )
    )


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
    return ok(
        _serialize(
            batch,
            items,
            _channel_names(db, list(batch.target_channel_ids or [])),
            _engine_names(db, list(batch.expected_engines or [])),
        )
    )


@router.post("/{batch_id}/dispatch", response_model=Envelope[dict])
def dispatch_batch(
    batch_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("publish.execute")),
    db: Session = Depends(get_db),
):
    """确认投喂：预检通过 + 准入/账号/版本复核通过，把计划落成发布任务。

    三步，顺序固定：
    1. 重算预检，未通过一律 blocked 并拒绝（关卡不写在页面上）；
    2. `apply_plan` 按「版本 × 渠道」建 pending 任务，幂等复用同批次既有任务；
    3. 冻结准入快照，写审计。事务在这里一次性提交，审计与任务同生同灭。
    """
    batch = db.scalar(
        select(DistributionBatch).where(
            DistributionBatch.project_id == ctx.project.id,
            DistributionBatch.id == batch_id,
        )
    )
    if batch is None:
        raise AppError("批次不存在或不属于当前项目", code="batch_not_found")
    if batch.status == DistributionBatchStatus.DISPATCHED:
        raise AppError("该批次已确认投喂，要再投一轮请新建批次", code="batch_already_dispatched")

    items = _items_of(db, batch.id)
    precheck = run_precheck(
        db, ctx.project.id,
        version_ids=[item.content_version_id for item in items],
        channel_ids=list(batch.target_channel_ids or []),
        expected_engine_ids=list(batch.expected_engines or []),
    )
    if not precheck["ready"]:
        apply_precheck(
            db, batch, version_ids=[item.content_version_id for item in items],
            project_id=ctx.project.id, expected_engine_ids=list(batch.expected_engines or []),
        )
        db.commit()
        raise AppError(
            f"预检未通过（{len(precheck['failed'])} 项），先补齐再投喂",
            code="batch_precheck_failed",
        )

    plan = apply_plan(
        db,
        project_id=ctx.project.id,
        batch=batch,
        items=items,
        actor_id=ctx.user.id,
        precheck=precheck,
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="distribution.dispatch",
        target_type="distribution_batch",
        target_id=batch.id,
        payload={
            "item_count": batch.item_count,
            "task_count": plan.task_count,
            "task_created": len(plan.created),
            "task_reused": len(plan.reused),
            "task_key": plan.task_keys[0] if plan.task_keys else None,
        },
    )
    db.commit()
    data = _serialize(
        batch,
        items,
        _channel_names(db, list(batch.target_channel_ids or [])),
        _engine_names(db, list(batch.expected_engines or [])),
    )
    data["task_ids"] = [str(task_id) for task_id in plan.created + plan.reused]
    return ok(data)
