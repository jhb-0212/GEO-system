"""内容新鲜度：按发布回执时间算「多久没更新」，18 个月为一条常识分界线。

口径三条（写进返回体，前端原样展示）：
1. 只认 `publish_receipts.received_at` 作为「已发布」的证据——与「只认人工确认引用」同一取向；
   发布任务标 published 但没有回执的，单列 `published_unverified`，不进新鲜度分母。
2. 过期与否由 `received_at` 实时计算，不落库标记：时钟或口径一变，标记不会留下历史假状态。
3. 母稿与渠道稿分开算；渠道维度只看挂在渠道上的稿件。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services.project_policy import policy_value
from app.models.content import ContentItem, ContentVersion
from app.models.publishing import PublishReceipt, PublishTask
from app.models.channel import Channel
from app.models.enums import ContentKind, PublishTaskStatus

DEFAULT_WINDOW_MONTHS = 18


def _add_months(moment: datetime, months: int) -> datetime:
    year = moment.year + (moment.month - 1 + months) // 12
    month = (moment.month - 1 + months) % 12 + 1
    day = min(moment.day, 28)
    return moment.replace(year=year, month=month, day=day)


def freshness_report(
    db: Session,
    project_id: uuid.UUID,
    *,
    months: int | None = None,
    limit: int = 200,
    now: datetime | None = None,
) -> dict:
    if months is None:  # 未显式传参时按项目口径；缺配置即通用默认 18 个月
        months = int(policy_value(db, project_id, "freshness.window_months"))
    now = (now or datetime.now(UTC)).astimezone(UTC)
    cutoff = _add_months(now, -months)

    items = list(
        db.scalars(
            select(ContentItem)
            .where(ContentItem.project_id == project_id)
            .order_by(ContentItem.created_at.asc())
        )
    )
    item_ids = [item.id for item in items]
    if not item_ids:
        return _empty(now, cutoff, months)

    versions = list(
        db.scalars(
            select(ContentVersion).where(ContentVersion.project_id == project_id)
        )
    )
    version_to_item = {row.id: row.item_id for row in versions}
    item_versions: dict[uuid.UUID, list[uuid.UUID]] = {}
    for row in versions:
        item_versions.setdefault(row.item_id, []).append(row.id)

    tasks = list(
        db.scalars(select(PublishTask).where(PublishTask.project_id == project_id))
    )
    task_versions = {row.id: row.version_id for row in tasks}

    receipts = list(
        db.scalars(
            select(PublishReceipt).where(PublishReceipt.project_id == project_id)
        )
    )
    latest_receipt: dict[uuid.UUID, datetime] = {}
    for receipt in receipts:
        item_id = version_to_item.get(task_versions.get(receipt.task_id))
        if item_id is None:
            continue
        when = receipt.received_at or receipt.created_at
        if when is None:
            continue
        current = latest_receipt.get(item_id)
        if current is None or when > current:
            latest_receipt[item_id] = when

    published_versions = {
        row.version_id
        for row in tasks
        if row.status == PublishTaskStatus.PUBLISHED
    }
    verified_items = {
        version_to_item[version_id]
        for version_id in published_versions
        if version_id in version_to_item
    }

    channels = {row.id: row for row in db.scalars(select(Channel).where(Channel.project_id == project_id))}

    rows: list[dict] = []
    counts = {"fresh": 0, "stale": 0, "unpublished": 0, "published_unverified": 0}
    by_channel: dict[str, dict] = {}
    for item in items:
        published_at = latest_receipt.get(item.id)
        if published_at is not None:
            status = "stale" if published_at < cutoff else "fresh"
        elif item.id in verified_items:
            status = "published_unverified"
        else:
            status = "unpublished"
        counts[status] += 1

        age_days = (now - published_at).days if published_at else None
        channel_key = str(item.channel_id) if item.channel_id else "unassigned"
        bucket = by_channel.setdefault(
            channel_key,
            {
                "channel_id": str(item.channel_id) if item.channel_id else None,
                "channel_name": channels[item.channel_id].name if item.channel_id in channels else "未挂渠道",
                "items": 0, "fresh": 0, "stale": 0, "unpublished": 0, "published_unverified": 0,
                "oldest_published_at": None,
            },
        )
        bucket["items"] += 1
        bucket[status] += 1
        if published_at and (bucket["oldest_published_at"] is None or published_at < bucket["oldest_published_at"]):
            bucket["oldest_published_at"] = published_at

        rows.append(
            {
                "item_id": str(item.id),
                "title": item.title,
                "kind": item.kind.value,
                "status": status,
                "channel_id": str(item.channel_id) if item.channel_id else None,
                "channel_name": bucket["channel_name"],
                "published_at": published_at.isoformat() if published_at else None,
                "age_days": age_days,
                "stale_by_days": (cutoff - published_at).days if published_at and published_at < cutoff else 0,
            }
        )

    rows.sort(key=lambda row: (row["status"] != "stale", -(row["age_days"] or -1)))
    published = counts["fresh"] + counts["stale"]
    channel_rows = []
    for bucket in by_channel.values():
        denom = bucket["fresh"] + bucket["stale"]
        channel_rows.append(
            {
                **{
                    key: bucket[key]
                    for key in ("channel_id", "channel_name", "items", "fresh", "stale", "unpublished", "published_unverified")
                },
                "stale_rate": round(bucket["stale"] / denom, 4) if denom else None,
                "oldest_published_at": bucket["oldest_published_at"].isoformat()
                if bucket["oldest_published_at"]
                else None,
            }
        )
    channel_rows.sort(key=lambda row: (-(row["stale_rate"] or 0), -row["items"]))

    return {
        "window_months": months,
        "cutoff": cutoff.isoformat(),
        "generated_at": now.isoformat(),
        "summary": {
            "total": len(items),
            "published": published,
            "fresh": counts["fresh"],
            "stale": counts["stale"],
            "unpublished": counts["unpublished"],
            "published_unverified": counts["published_unverified"],
            "stale_rate": round(counts["stale"] / published, 4) if published else None,
            "masters": sum(1 for item in items if item.kind == ContentKind.MASTER),
            "channel_copies": sum(1 for item in items if item.kind == ContentKind.CHANNEL),
        },
        "by_channel": channel_rows,
        "items": rows[:limit],
        "notes": [
            f"过期判定线：最近一条发布回执距今超过 {months} 个月。",
            "只认回执 `received_at`；发布任务标 published 但无回执的列 published_unverified，不进新鲜度分母。",
            "过期标记实时计算、不落库，避免口径调整后留下历史假状态。",
        ],
    }


def _empty(now: datetime, cutoff: datetime, months: int) -> dict:
    return {
        "window_months": months,
        "cutoff": cutoff.isoformat(),
        "generated_at": now.isoformat(),
        "summary": {
            "total": 0, "published": 0, "fresh": 0, "stale": 0, "unpublished": 0,
            "published_unverified": 0, "stale_rate": None, "masters": 0, "channel_copies": 0,
        },
        "by_channel": [],
        "items": [],
        "notes": ["尚无内容条目；新鲜度从有回执的发布开始算。"],
    }
