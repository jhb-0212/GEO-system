"""品牌口径的读取与治理统计，从 `api/brand.py` 下沉。

只负责取数与组装；「什么算就绪」的判定留在 api（属于产品口径）。
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BrandProfile, Channel, Material


def profile_row(
    db: Session, project_id: uuid.UUID, *, for_update: bool = False
) -> BrandProfile | None:
    query = select(BrandProfile).where(BrandProfile.project_id == project_id)
    if for_update:
        query = query.with_for_update()
    return db.scalar(query)


def brand_payload(profile: BrandProfile | None, vocabulary) -> dict:
    return {
        "configured": profile is not None,
        "canonical_name": profile.canonical_name if profile else None,
        "aliases": (profile.aliases or []) if profile else [],
        "identifiers": (profile.identifiers or []) if profile else [],
        "owned_domains": (profile.owned_domains or []) if profile else [],
        "notes": profile.notes if profile else None,
        "is_active": profile.is_active if profile else False,
        "updated_at": profile.updated_at if profile else None,
        # 生效词表：采集/统计实际用的就是这几组，前端据此解释报表口径。
        "effective_mention_terms": vocabulary.mention_terms,
        "effective_identifier_terms": vocabulary.identifier_terms,
        "effective_owned_domains": vocabulary.owned_domains,
    }


def materials_summary(db: Session, project_id: uuid.UUID) -> tuple[int, dict[str, int]]:
    total = (
        db.scalar(
            select(func.count()).select_from(Material).where(Material.project_id == project_id)
        )
        or 0
    )
    by_category = {
        str(category): int(count)
        for category, count in db.execute(
            select(Material.category, func.count())
            .where(Material.project_id == project_id)
            .group_by(Material.category)
        ).all()
    }
    return int(total), by_category


def _owner_filter(project_id: uuid.UUID) -> list:
    return [
        Channel.project_id == project_id,
        Channel.owner_name.is_not(None),
        func.length(func.trim(Channel.owner_name)) > 0,
    ]


def channel_owner_summary(
    db: Session, project_id: uuid.UUID
) -> tuple[int, int, list[dict]]:
    """返回（渠道总数、已指定负责人的渠道数、按负责人聚合的清单）。"""
    total = (
        db.scalar(
            select(func.count()).select_from(Channel).where(Channel.project_id == project_id)
        )
        or 0
    )
    with_owner = (
        db.scalar(
            select(func.count())
            .select_from(Channel)
            .where(*_owner_filter(project_id))
        )
        or 0
    )
    owners = [
        {"name": name, "contact": contact, "channels": int(count)}
        for name, contact, count in db.execute(
            select(Channel.owner_name, Channel.owner_contact, func.count())
            .where(*_owner_filter(project_id))
            .group_by(Channel.owner_name, Channel.owner_contact)
            .order_by(func.count().desc(), Channel.owner_name)
        ).all()
    ]
    return int(total), int(with_owner), owners
