"""待归类渠道队列：`review_pending` 渠道 + 它们已经带来的引用覆盖。

用途是「这个渠道还在待归类，但已经有多少引用落在它身上」——运营据此决定先归哪一批。
口径与渠道详情一致：引用数按引用行数、样本数按 `sample_id` 去重、最近采样取 `max(sampled_at)`。
一次分组聚合出所有渠道的数字，避免每个渠道各查两次。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Channel, MonitoringCitation, MonitoringSample
from app.models.enums import ChannelStatus


def page_review_pending(
    db: Session,
    project_id: uuid.UUID,
    *,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[dict[str, Any]]]:
    """返回 (待归类渠道总数, 当前页渠道及其引用统计)。"""
    pending = [Channel.project_id == project_id, Channel.status == ChannelStatus.REVIEW_PENDING]
    total = int(db.scalar(select(func.count()).select_from(Channel).where(*pending)) or 0)
    channels = db.scalars(
        select(Channel)
        .where(*pending)
        .order_by(Channel.code)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    stats: dict[uuid.UUID, Any] = {}
    if channels:
        stats_rows = db.execute(
            select(
                MonitoringCitation.channel_id,
                func.count().label("citation_count"),
                func.count(func.distinct(MonitoringCitation.sample_id)).label("sample_count"),
                func.max(MonitoringSample.sampled_at).label("last_sampled_at"),
            )
            .join(MonitoringSample, MonitoringCitation.sample_id == MonitoringSample.id)
            .where(
                MonitoringCitation.project_id == project_id,
                MonitoringCitation.channel_id.in_([channel.id for channel in channels]),
                MonitoringSample.project_id == project_id,
            )
            .group_by(MonitoringCitation.channel_id)
        ).all()
        stats = {row.channel_id: row for row in stats_rows}

    items = []
    for channel in channels:
        row = stats.get(channel.id)
        items.append(
            {
                "channel_id": str(channel.id),
                "code": channel.code,
                "name": channel.name,
                "primary_domain": channel.primary_domain,
                "citation_count": int(row.citation_count) if row else 0,
                "sample_count": int(row.sample_count) if row else 0,
                "last_sampled_at": row.last_sampled_at if row else None,
            }
        )
    return total, items
