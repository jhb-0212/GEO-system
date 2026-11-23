"""渠道改编 API：母稿派生渠道稿、列出血缘、跟版同步、项目级一致性清单。"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.content import _content_hash
from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, PagedEnvelope, ok, ok_page
from app.core.errors import AppError
from app.db.session import get_db
from app.models import Channel, ContentDerivation, ContentItem, ContentVersion
from app.models.enums import ContentKind, ContentStatus
from app.services.audit import record_audit
from app.services.content_derivation import rule_for, run_checks

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/contents",
    tags=["渠道改编"],
    responses=COMMON_ERRORS,
)


class DeriveIn(BaseModel):
    channel_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
    title_suffix: str | None = Field(default=None, max_length=60)


def _master_with_version(db: Session, project_id: uuid.UUID, item_id: uuid.UUID) -> tuple[ContentItem, ContentVersion]:
    item = db.scalar(select(ContentItem).where(ContentItem.project_id == project_id, ContentItem.id == item_id))
    if item is None:
        raise AppError("内容不存在或不属于当前项目", code="content_not_found")
    if item.kind != ContentKind.MASTER:
        raise AppError("只有母稿能派生出渠道稿", code="not_master")
    if item.current_version_id is None:
        raise AppError("母稿还没有任何版本，先写正文", code="master_without_version")
    version = db.scalar(
        select(ContentVersion).where(ContentVersion.id == item.current_version_id, ContentVersion.project_id == project_id)
    )
    if version is None:
        raise AppError("母稿当前版本缺失", code="master_version_missing")
    return item, version


def _require_approved(version: ContentVersion) -> None:
    """只有审核通过的母稿才能改编：未过审的正文不往渠道上复制。"""
    if version.status != ContentStatus.APPROVED:
        raise AppError("母稿当前版本尚未审核通过，不能改编", code="master_version_not_approved")


def _serialize(row: ContentDerivation, master_hash: str, channel: Channel | None, item: ContentItem | None, version: ContentVersion | None) -> dict:
    stale = row.source_content_hash != master_hash
    return {
        "id": str(row.id),
        "channel_item_id": str(row.channel_item_id),
        "channel_item_title": item.title if item else None,
        "channel_name": channel.name if channel else None,
        "channel_category": channel.category.value if channel else None,
        "channel_category_label": rule_for(channel.category.value if channel else None)["label"],
        "item_status": item.status.value if item else None,
        "version_status": version.status.value if version else None,
        "source_content_hash": row.source_content_hash,
        "source_version_id": str(row.source_version_id),
        "stale": stale,
        "checks": row.checks,
        "created_at": row.created_at,
        "synced_at": row.synced_at,
    }


def _load_derivations(db: Session, project_id: uuid.UUID, master_item_id: uuid.UUID | None) -> list[ContentDerivation]:
    filters = [ContentDerivation.project_id == project_id]
    if master_item_id is not None:
        filters.append(ContentDerivation.master_item_id == master_item_id)
    return list(db.scalars(select(ContentDerivation).where(*filters).order_by(ContentDerivation.created_at.desc())).all())


def _row_payload(db: Session, project_id: uuid.UUID, row: ContentDerivation, master_hash: str) -> dict:
    channel = db.scalar(select(Channel).where(Channel.id == row.channel_id))
    item = db.scalar(select(ContentItem).where(ContentItem.id == row.channel_item_id))
    version = db.scalar(select(ContentVersion).where(ContentVersion.id == item.current_version_id)) if item and item.current_version_id else None
    return _serialize(row, master_hash, channel, item, version)


@router.post("/{item_id}/derive", status_code=201, response_model=Envelope[dict])
def derive_channels(
    item_id: uuid.UUID,
    payload: DeriveIn,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
):
    master, version = _master_with_version(db, ctx.project.id, item_id)
    _require_approved(version)

    channels = list(
        db.scalars(
            select(Channel).where(Channel.project_id == ctx.project.id, Channel.id.in_(payload.channel_ids))
        ).all()
    )
    found_ids = {channel.id for channel in channels}
    missing = [str(cid) for cid in payload.channel_ids if cid not in found_ids]
    if missing:
        raise AppError("以下渠道不存在或不属于当前项目：" + "、".join(missing), code="channel_not_found")

    existing = {
        row.channel_id
        for row in _load_derivations(db, ctx.project.id, master.id)
    }
    duplicated = [channel.name for channel in channels if channel.id in existing]
    if duplicated:
        raise AppError("这些渠道已经有改编稿，先删掉旧稿或直接在其上跟版：" + "、".join(duplicated), code="derivation_exists")

    created: list[ContentDerivation] = []
    for channel in channels:
        rule = rule_for(channel.category.value)
        title = f"{master.title}（{rule['label']}）"
        if payload.title_suffix:
            title = f"{title} {payload.title_suffix.strip()}"
        channel_item = ContentItem(
            project_id=ctx.project.id,
            kind=ContentKind.CHANNEL,
            parent_id=master.id,
            channel_id=channel.id,
            title=title[:255],
            status=ContentStatus.DRAFT,
            created_by=ctx.user.id,
        )
        db.add(channel_item)
        db.flush()

        channel_version = ContentVersion(
            project_id=ctx.project.id,
            item_id=channel_item.id,
            version_no=1,
            body=version.body,
            content_hash=_content_hash(version.body),
            status=ContentStatus.DRAFT,
            change_note=f"由母稿「{master.title}」v{version.version_no} 改编",
            created_by=ctx.user.id,
        )
        db.add(channel_version)
        db.flush()
        channel_item.current_version_id = channel_version.id

        checks = run_checks(version.body, channel.category.value)
        derivation = ContentDerivation(
            project_id=ctx.project.id,
            master_item_id=master.id,
            channel_item_id=channel_item.id,
            channel_id=channel.id,
            source_version_id=version.id,
            source_content_hash=version.content_hash,
            checks=checks,
            created_by=ctx.user.id,
        )
        db.add(derivation)
        db.flush()
        created.append(derivation)

        record_audit(
            db,
            project_id=ctx.project.id,
            actor_id=ctx.user.id,
            action="content.derive_channel",
            target_type="content_item",
            target_id=channel_item.id,
            payload={"master_item_id": str(master.id), "channel_id": str(channel.id), "checks": [c["key"] for c in checks if not c["ok"]]},
        )
    db.commit()

    return ok(
        {
            "master_item_id": str(master.id),
            "master_hash": version.content_hash,
            "created": [_row_payload(db, ctx.project.id, row, version.content_hash) for row in created],
        }
    )


@router.get("/{item_id}/derivations", response_model=Envelope[dict])
def list_derivations(
    item_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
):
    master, version = _master_with_version(db, ctx.project.id, item_id)
    rows = _load_derivations(db, ctx.project.id, master.id)
    items = [_row_payload(db, ctx.project.id, row, version.content_hash) for row in rows]
    return ok(
        {
            "master_item_id": str(master.id),
            "master_title": master.title,
            "master_version_no": version.version_no,
            "master_version_status": version.status.value,
            "master_hash": version.content_hash,
            "derivations": items,
            "stale_count": sum(1 for item in items if item["stale"]),
        }
    )


@router.post("/{item_id}/derivations/{derivation_id}/sync", response_model=Envelope[dict])
def sync_derivation(
    item_id: uuid.UUID,
    derivation_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
):
    """把母稿当前版本正文拉一份到渠道稿（新版本），只做透传，不自动改写。"""
    master, version = _master_with_version(db, ctx.project.id, item_id)
    _require_approved(version)

    derivation = db.scalar(
        select(ContentDerivation).where(
            ContentDerivation.project_id == ctx.project.id,
            ContentDerivation.id == derivation_id,
            ContentDerivation.master_item_id == master.id,
        )
    )
    if derivation is None:
        raise AppError("改编记录不存在", code="derivation_not_found")

    channel_item = db.scalar(select(ContentItem).where(ContentItem.id == derivation.channel_item_id))
    channel = db.scalar(select(Channel).where(Channel.id == derivation.channel_id))
    if channel_item is None or channel is None:
        raise AppError("渠道稿或渠道已不存在", code="derivation_orphaned")

    next_no = int(
        db.scalar(select(func.max(ContentVersion.version_no)).where(ContentVersion.item_id == channel_item.id)) or 0
    ) + 1
    channel_version = ContentVersion(
        project_id=ctx.project.id,
        item_id=channel_item.id,
        version_no=next_no,
        body=version.body,
        content_hash=_content_hash(version.body),
        status=ContentStatus.DRAFT,
        change_note=f"跟随母稿「{master.title}」v{version.version_no} 更新",
        created_by=ctx.user.id,
    )
    db.add(channel_version)
    db.flush()
    channel_item.current_version_id = channel_version.id
    # 渠道稿被改过就回到 draft：跟版后必须重新审核，不能沿用旧的通过状态
    channel_item.status = ContentStatus.DRAFT

    derivation.source_version_id = version.id
    derivation.source_content_hash = version.content_hash
    derivation.checks = run_checks(version.body, channel.category.value)
    derivation.synced_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="content.derive_sync",
        target_type="content_item",
        target_id=channel_item.id,
        payload={"master_item_id": str(master.id), "version_no": next_no, "content_hash": channel_version.content_hash},
    )
    db.commit()
    return ok(_row_payload(db, ctx.project.id, derivation, version.content_hash))


@router.get("/derivations", response_model=PagedEnvelope[dict])
def consistency_list(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    stale_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """项目级一致性清单：按「母稿当前哈希 vs 改编来源哈希」判定是否跟版。"""
    rows = _load_derivations(db, ctx.project.id, None)
    items: list[dict] = []
    for row in rows:
        master = db.scalar(select(ContentItem).where(ContentItem.id == row.master_item_id))
        master_version = None
        if master and master.current_version_id:
            master_version = db.scalar(select(ContentVersion).where(ContentVersion.id == master.current_version_id))
        master_hash = master_version.content_hash if master_version else ""
        payload = _row_payload(db, ctx.project.id, row, master_hash)
        payload["master_item_title"] = master.title if master else None
        payload["master_version_no"] = master_version.version_no if master_version else None
        if stale_only and not payload["stale"]:
            continue
        items.append(payload)

    total = len(items)
    start = (page - 1) * page_size
    return ok_page(items[start:start + page_size], page=page, page_size=page_size, total=total)
