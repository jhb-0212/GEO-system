"""母稿改编（渠道派生稿）的读取口径。

改造前这个文件是典型的 N+1：项目级一致性清单先把所有改编记录读进内存，
然后每行再查 5 次（母稿、母稿版本、渠道、渠道稿、渠道稿版本），最后在内存里切片分页。
500 条改编记录就是 2500 次查询，而且 `total` 只是「已加载行数」，不是真实总数。

现在一条联表语句同时服务计数与分页：
- 母稿、母稿版本、渠道、渠道稿、渠道稿版本全部 join 进来；
- 「是否跟版」`stale` 直接由 SQL 比较 `source_content_hash` 与母稿当前版本哈希得出，
  因此 `stale_only` 也能在数据库侧过滤，而不是先取全量再筛。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ResourceMissingError
from app.models import Channel, ContentDerivation, ContentItem, ContentVersion
from app.models.enums import ContentStatus
from app.services.content_derivation import rule_for

_master_item = ContentItem.__table__.alias("master_item")
_master_version = ContentVersion.__table__.alias("master_version")


def _joined_statement(project_id: uuid.UUID, master_item_id: uuid.UUID | None = None) -> Select:
    stmt = (
        select(
            ContentDerivation,
            Channel,
            ContentItem,
            ContentVersion,
            _master_item.c.title,
            _master_version.c.version_no,
            _master_version.c.content_hash,
        )
        .outerjoin(Channel, Channel.id == ContentDerivation.channel_id)
        .outerjoin(ContentItem, ContentItem.id == ContentDerivation.channel_item_id)
        .outerjoin(ContentVersion, ContentVersion.id == ContentItem.current_version_id)
        .outerjoin(_master_item, _master_item.c.id == ContentDerivation.master_item_id)
        .outerjoin(_master_version, _master_version.c.id == _master_item.c.current_version_id)
        .where(ContentDerivation.project_id == project_id)
    )
    if master_item_id is not None:
        stmt = stmt.where(ContentDerivation.master_item_id == master_item_id)
    return stmt


def _stale_expression() -> Any:
    """母稿当前哈希与改编来源哈希不一致即未跟版；母稿缺失按「未跟版」处理。"""
    return ContentDerivation.source_content_hash != func.coalesce(_master_version.c.content_hash, "")


def _payload(row: Any) -> dict[str, Any]:
    (
        derivation,
        channel,
        channel_item,
        channel_version,
        master_title,
        master_version_no,
        master_hash,
    ) = row
    stale = derivation.source_content_hash != (master_hash or "")
    return {
        "id": str(derivation.id),
        "master_item_id": str(derivation.master_item_id),
        "channel_id": str(derivation.channel_id),
        "channel_item_id": str(derivation.channel_item_id),
        "channel_item_title": channel_item.title if channel_item else None,
        "channel_name": channel.name if channel else None,
        "channel_category": channel.category.value if channel else None,
        "channel_category_label": rule_for(channel.category.value if channel else None)["label"],
        "item_status": channel_item.status.value if channel_item else None,
        "version_status": channel_version.status.value if channel_version else None,
        "source_content_hash": derivation.source_content_hash,
        "source_version_id": str(derivation.source_version_id),
        "stale": stale,
        "checks": derivation.checks,
        "created_at": derivation.created_at,
        "synced_at": derivation.synced_at,
    }


def master_with_version(
    db: Session, project_id: uuid.UUID, item_id: uuid.UUID
) -> tuple[ContentItem, ContentVersion]:
    item = db.scalar(
        select(ContentItem).where(ContentItem.project_id == project_id, ContentItem.id == item_id)
    )
    if item is None:
        raise ResourceMissingError("母稿不存在")
    if not item.current_version_id:
        raise ResourceMissingError("母稿没有可用版本")
    version = db.scalar(
        select(ContentVersion).where(
            ContentVersion.id == item.current_version_id,
            ContentVersion.project_id == project_id,
        )
    )
    if version is None:
        raise ResourceMissingError("母稿当前版本不存在")
    return item, version


def require_approved(version: ContentVersion) -> None:
    """只有审核通过的母稿才能改编：未过审的正文不往渠道上复制。"""
    if version.status != ContentStatus.APPROVED:
        raise AppError("母稿当前版本尚未审核通过，不能改编", code="master_version_not_approved")


def list_for_master(
    db: Session, project_id: uuid.UUID, master_item_id: uuid.UUID
) -> list[dict[str, Any]]:
    """某个母稿下的改编记录（数量天然有限，不做分页）。"""
    rows = db.execute(
        _joined_statement(project_id, master_item_id).order_by(
            ContentDerivation.created_at.desc()
        )
    ).all()
    return [_payload(row) for row in rows]


def page_derivations(
    db: Session,
    project_id: uuid.UUID,
    *,
    stale_only: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[dict[str, Any]]]:
    """项目级改编一致性清单：数据库侧过滤未跟版，数据库侧分页。"""
    stmt = _joined_statement(project_id)
    if stale_only:
        stmt = stmt.where(_stale_expression())

    total = int(
        db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    )
    rows = db.execute(
        stmt.order_by(ContentDerivation.created_at.desc(), ContentDerivation.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = []
    for row in rows:
        payload = _payload(row)
        payload["master_item_title"] = row[4]
        payload["master_version_no"] = row[5]
        items.append(payload)
    return total, items
