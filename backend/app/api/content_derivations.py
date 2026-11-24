"""渠道改编 API：母稿派生渠道稿、列出血缘、跟版同步、项目级一致性清单。"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, PagedEnvelope, ok, ok_page
from app.core.errors import AppError
from app.db.session import get_db
from app.models import Channel, ContentDerivation, ContentItem, ContentVersion
from app.models.enums import ContentKind, ContentStatus
from app.services.audit import record_audit
from app.services.content_derivation import rule_for, run_checks
from app.services.derivations import (
    channel_target,
    channels_by_ids,
    derivation_row,
    next_version_no,
)
from app.services.derivations import (
    list_for_master,
    master_with_version,
    page_derivations,
    require_approved,
)
from app.services.hashing import content_hash as _content_hash

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/contents",
    tags=["渠道改编"],
    responses=COMMON_ERRORS,
)


class DeriveIn(BaseModel):
    channel_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
    title_suffix: str | None = Field(default=None, max_length=60)


@router.post("/{item_id}/derive", status_code=201, response_model=Envelope[dict])
def derive_channels(
    item_id: uuid.UUID,
    payload: DeriveIn,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
):
    master, version = master_with_version(db, ctx.project.id, item_id)
    require_approved(version)

    channels = channels_by_ids(db, ctx.project.id, payload.channel_ids)
    found_ids = {channel.id for channel in channels}
    missing = [str(cid) for cid in payload.channel_ids if cid not in found_ids]
    if missing:
        raise AppError("以下渠道不存在或不属于当前项目：" + "、".join(missing), code="channel_not_found")

    # list_for_master 的 payload 里 id 一律序列化为字符串，比较也要用同一形态。
    existing = {row["channel_id"] for row in list_for_master(db, ctx.project.id, master.id)}
    duplicated = [channel.name for channel in channels if str(channel.id) in existing]
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

    created_rows = {row["id"]: row for row in list_for_master(db, ctx.project.id, master.id)}
    return ok(
        {
            "master_item_id": str(master.id),
            "master_hash": version.content_hash,
            "created": [created_rows[str(row.id)] for row in created if str(row.id) in created_rows],
        }
    )


@router.get("/{item_id}/derivations", response_model=Envelope[dict])
def list_derivations(
    item_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
):
    master, version = master_with_version(db, ctx.project.id, item_id)
    items = list_for_master(db, ctx.project.id, master.id)
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
    master, version = master_with_version(db, ctx.project.id, item_id)
    require_approved(version)

    derivation = derivation_row(db, ctx.project.id, master.id, derivation_id)
    channel_item, channel = channel_target(db, derivation)
    if channel_item is None or channel is None:
        raise AppError("渠道稿或渠道已不存在", code="derivation_orphaned")

    next_no = next_version_no(db, channel_item.id)
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
    refreshed = {row["id"]: row for row in list_for_master(db, ctx.project.id, master.id)}
    return ok(refreshed[str(derivation.id)])


@router.get("/derivations", response_model=PagedEnvelope[dict])
def consistency_list(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    stale_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """项目级一致性清单：按「母稿当前哈希 vs 改编来源哈希」判定是否跟版。

    未跟版过滤与分页都在数据库侧完成，不再先把全部改编记录读进内存。
    """
    total, items = page_derivations(
        db, ctx.project.id, stale_only=stale_only, page=page, page_size=page_size
    )
    return ok_page(items, page=page, page_size=page_size, total=total)
