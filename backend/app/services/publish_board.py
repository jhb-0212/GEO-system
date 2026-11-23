"""发布回链看板：发出去的页面 → 能否被检索到 → 是否已被 AI 引用，同一条链三段全列。

口径边界：
- 只读聚合，不改发布状态；
- 「已被引用」只认人工复核通过的引用（与诊断报告的信源口径一致），未复核不算；
- 可见性检测失败的记录保持「未查成」状态，不计入「未收录」。
"""

from __future__ import annotations

import uuid
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Channel,
    ContentItem,
    ContentVersion,
    MonitoringCitation,
    PublishReceipt,
    PublishTask,
)
from app.models.enums import CitationReviewStatus
from app.services.publish_visibility import latest_checks


def host_of(url: str | None) -> str:
    if not url:
        return ""
    try:
        host = (urlparse(url).hostname or "").casefold()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def board(db: Session, project_id: uuid.UUID, *, limit: int = 200) -> dict:
    rows = db.execute(
        select(
            PublishReceipt,
            PublishTask.serial_no,
            Channel.name.label("channel_name"),
            ContentItem.title.label("content_title"),
        )
        .join(PublishTask, PublishTask.id == PublishReceipt.task_id)
        .join(ContentVersion, ContentVersion.id == PublishTask.version_id)
        .join(ContentItem, ContentItem.id == ContentVersion.item_id)
        .outerjoin(Channel, Channel.id == PublishTask.channel_id)
        .where(PublishReceipt.project_id == project_id)
        .order_by(PublishReceipt.received_at.desc(), PublishReceipt.id.desc())
        .limit(limit)
    ).all()

    checks = {row["receipt_id"]: row for row in latest_checks(db, project_id, limit=limit * 2)}
    cited_domains = set(
        db.scalars(
            select(MonitoringCitation.domain)
            .where(
                MonitoringCitation.project_id == project_id,
                MonitoringCitation.review_status == CitationReviewStatus.MANUAL_CONFIRMED,
                MonitoringCitation.domain.is_not(None),
            )
            .distinct()
        ).all()
    )
    cited_domains = {domain.casefold() for domain in cited_domains if domain}

    items = []
    for receipt, serial_no, channel_name, content_title in rows:
        host = host_of(receipt.published_url)
        check = checks.get(str(receipt.id))
        items.append(
            {
                "receipt_id": str(receipt.id),
                "task_serial_no": serial_no,
                "channel_name": channel_name,
                "content_title": content_title,
                "published_url": receipt.published_url,
                "published_host": host or None,
                "received_at": receipt.received_at,
                "verified_at": receipt.verified_at,
                "visibility_checked_at": check["checked_at"] if check else None,
                "visibility_matched": bool(check["matched"]) if check else None,
                "visibility_position": check["position"] if check else None,
                "visibility_error_code": check["error_code"] if check else None,
                "cited": bool(host) and host in cited_domains,
            }
        )

    total = len(items)
    checked = sum(1 for item in items if item["visibility_checked_at"] is not None)
    matched = sum(1 for item in items if item["visibility_matched"])
    errored = sum(1 for item in items if item["visibility_error_code"])
    cited = sum(1 for item in items if item["cited"])

    return {
        "items": items,
        "summary": {
            "total_receipts": total,
            "visibility_checked": checked,
            "visibility_matched": matched,
            "visibility_errored": errored,
            "cited": cited,
            # 分母口径：可见性用「已检测」；引用用「全部回执」
            "visibility_match_rate": round(matched / (checked - errored), 4) if (checked - errored) else None,
            "cited_rate": round(cited / total, 4) if total else None,
        },
        "caveats": [
            "「已被引用」只统计人工复核通过的引用，未复核与已驳回不算。",
            "检测失败的记录停在「未查成」，不并入「未收录」。",
        ],
    }


def count_receipts(db: Session, project_id: uuid.UUID) -> int:
    return int(db.scalar(select(func.count()).where(PublishReceipt.project_id == project_id)) or 0)
