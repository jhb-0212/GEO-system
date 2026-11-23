"""页面三态：可访问 / 可检索 / 被引用。

三层原本各自观测、各自成页，运营看到的却是三个孤立的数字：
- 可访问：`publish_receipts.last_reachable`（回抓页面本身，404/410 才算不可访问）；
- 可检索：`publish_visibility_checks`（搜索引擎能否搜到，URL 精确匹配）；
- 被引用：`monitoring_citations` 里 URL 精确命中且人工复核的条数。

本模块只把三者并到一条页面记录上，**不合成任何分数、不给结论**。任一态未观测就写
`unknown`，绝不把"没查过"写成"没有"。
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Channel,
    ContentItem,
    ContentVersion,
    MonitoringCitation,
    PublishReceipt,
    PublishTask,
    PublishVisibilityCheck,
)
from app.models.enums import CitationReviewStatus
from app.services.citation_attribution import url_key


def page_visibility(db: Session, project_id: uuid.UUID, *, limit: int = 50) -> dict:
    receipts = list(
        db.scalars(
            select(PublishReceipt).where(PublishReceipt.project_id == project_id).order_by(
                PublishReceipt.received_at.desc()
            )
        )
    )

    checks: dict[uuid.UUID, PublishVisibilityCheck] = {}
    for row in db.scalars(
        select(PublishVisibilityCheck)
        .where(PublishVisibilityCheck.project_id == project_id)
        .order_by(PublishVisibilityCheck.checked_at.desc())
    ):
        checks.setdefault(row.receipt_id, row)

    channels: dict[uuid.UUID, str] = {
        row.id: row.name for row in db.scalars(select(Channel).where(Channel.project_id == project_id))
    }

    tasks: dict[uuid.UUID, PublishTask] = {
        row.id: row for row in db.scalars(select(PublishTask).where(PublishTask.project_id == project_id))
    }
    versions: dict[uuid.UUID, ContentVersion] = {
        row.id: row for row in db.scalars(select(ContentVersion).where(ContentVersion.project_id == project_id))
    }
    items: dict[uuid.UUID, ContentItem] = {
        row.id: row for row in db.scalars(select(ContentItem).where(ContentItem.project_id == project_id))
    }

    cited: dict[str, int] = defaultdict(int)
    for row in db.scalars(
        select(MonitoringCitation).where(
            MonitoringCitation.project_id == project_id,
            MonitoringCitation.review_status == CitationReviewStatus.MANUAL_CONFIRMED,
            MonitoringCitation.raw_url.is_not(None),
        )
    ):
        cited[url_key(row.raw_url)] += 1

    pages: list[dict] = []
    for receipt in receipts:
        task = tasks.get(receipt.task_id)
        version = versions.get(task.version_id) if task and task.version_id else None
        item = items.get(version.item_id) if version and version.item_id else None
        channel_name = channels.get(item.channel_id) if item and item.channel_id else None

        key = url_key(receipt.published_url)
        check = checks.get(receipt.id)

        accessible = "unknown" if receipt.last_reachable is None else ("yes" if receipt.last_reachable else "no")
        if check is None:
            searchable, search_detail = "unknown", "未检测"
        elif check.error_code:
            searchable, search_detail = "unknown", f"查询失败：{check.error_code}"
        else:
            searchable = "yes" if check.matched else "no"
            search_detail = f"第 {check.position} 位" if check.position else "未命中"

        pages.append(
            {
                "receipt_id": str(receipt.id),
                "url": receipt.published_url,
                "title": item.title if item else None,
                "channel": channel_name,
                "received_at": receipt.received_at.isoformat() if receipt.received_at else None,
                "accessible": accessible,
                "accessible_status": receipt.last_reachability_status,
                "accessible_at": receipt.last_reachability_at.isoformat() if receipt.last_reachability_at else None,
                "searchable": searchable,
                "searchable_detail": search_detail,
                "searchable_query": check.query if check else None,
                "cited": cited.get(key, 0),
            }
        )

    summary = {
        "receipts": len(pages),
        "accessible": {
            "yes": sum(1 for p in pages if p["accessible"] == "yes"),
            "no": sum(1 for p in pages if p["accessible"] == "no"),
            "unknown": sum(1 for p in pages if p["accessible"] == "unknown"),
        },
        "searchable": {
            "yes": sum(1 for p in pages if p["searchable"] == "yes"),
            "no": sum(1 for p in pages if p["searchable"] == "no"),
            "unknown": sum(1 for p in pages if p["searchable"] == "unknown"),
        },
        "cited_pages": sum(1 for p in pages if p["cited"] > 0),
        "cited_total": sum(p["cited"] for p in pages),
    }

    return {
        "summary": summary,
        "pages": pages[:limit],
        "notes": [
            "三态各自独立观测，不合成分数；unknown = 没查过，不等于没有。",
            "被引用只认 URL 精确命中（归一化后比较），且必须是人工复核过的引用。",
            "可检索=false 只代表本次查询没搜到，可能是排名/过滤导致，不等同于未收录。",
        ],
    }
