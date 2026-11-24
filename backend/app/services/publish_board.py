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
    DistributionBatch,
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
                # 三态之一：页面还在不在；与「已被收录」「已被引用」分别观测
                "reachable": receipt.last_reachable,
                "reachability_status": receipt.last_reachability_status,
                "reachability_error": receipt.last_reachability_error,
                "reachability_checked_at": receipt.last_reachability_at,
            }
        )

    total = len(items)
    checked = sum(1 for item in items if item["visibility_checked_at"] is not None)
    matched = sum(1 for item in items if item["visibility_matched"])
    errored = sum(1 for item in items if item["visibility_error_code"])
    cited = sum(1 for item in items if item["cited"])
    reach_checked = sum(1 for item in items if item["reachability_checked_at"] is not None)
    reachable = sum(1 for item in items if item["reachable"] is True)
    unreachable = sum(1 for item in items if item["reachable"] is False)

    return {
        "items": items,
        "summary": {
            "total_receipts": total,
            "visibility_checked": checked,
            "visibility_matched": matched,
            "visibility_errored": errored,
            "cited": cited,
            "reachability_checked": reach_checked,
            "reachable": reachable,
            "unreachable": unreachable,
            # 分母口径：可见性用「已检测」；引用用「全部回执」
            "visibility_match_rate": round(matched / (checked - errored), 4) if (checked - errored) else None,
            "cited_rate": round(cited / total, 4) if total else None,
            "reachable_rate": round(reachable / reach_checked, 4) if reach_checked else None,
        },
        "caveats": [
            "「已被引用」只统计人工复核通过的引用，未复核与已驳回不算。",
            "检测失败的记录停在「未查成」，不并入「未收录」。",
            "「可访问」是回抓页面本身，网络失败不改历史结论，也不等于被删除。",
        ],
    }


def count_receipts(db: Session, project_id: uuid.UUID) -> int:
    return int(db.scalar(select(func.count()).where(PublishReceipt.project_id == project_id)) or 0)


def batches(db: Session, project_id: uuid.UUID, *, limit: int = 50) -> dict:
    """按投喂批次聚合的三段证据：任务 → 回执 → 收录/引用。

    为什么按批次：单条内容的中断原因散在四个页面（任务、回执、可见性、引用），
    人看不到「这一批整体卡在哪一段」。批次是运营一次动作的单位，聚合到批次才可判断。
    口径边界：
    - 只统计 `source_batch_id` 不为空的任务（手工建单不属于任何批次）；
    - 「已回执」「已收录」「已被引用」三者独立观测，不合并成单一成功率；
    - 没确认投喂（`task_count=0`）的批次也列出，标 `stage=not_dispatched`，
      否则「确认了但没生成任务」这种断链会被藏起来。
    """
    batch_rows = db.scalars(
        select(DistributionBatch)
        .where(DistributionBatch.project_id == project_id)
        .order_by(DistributionBatch.created_at.desc())
        .limit(limit)
    ).all()
    if not batch_rows:
        return {
            "items": [],
            "summary": {"batches": 0, "tasks": 0, "receipts": 0},
            "caveats": ["手工建单的发布任务不归属任何批次，不在本视图内。"],
        }

    tasks = db.execute(
        select(
            PublishTask.source_batch_id,
            PublishTask.id,
            PublishTask.status,
            Channel.name.label("channel_name"),
        )
        .outerjoin(Channel, Channel.id == PublishTask.channel_id)
        .where(
            PublishTask.project_id == project_id,
            PublishTask.source_batch_id.in_([batch.id for batch in batch_rows]),
        )
    ).all()
    task_ids = {task_id for _batch, task_id, _status, _channel in tasks}
    receipts = {
        row.task_id: row
        for row in db.scalars(
            select(PublishReceipt).where(
                PublishReceipt.project_id == project_id,
                PublishReceipt.task_id.in_(task_ids) if task_ids else False,
            )
        ).all()
    } if task_ids else {}

    checks = {
        row["receipt_id"]: row
        for row in latest_checks(db, project_id, limit=max(len(receipts) * 2, 50))
    }
    cited_domains = {
        domain.casefold()
        for domain in db.scalars(
            select(MonitoringCitation.domain)
            .where(
                MonitoringCitation.project_id == project_id,
                MonitoringCitation.review_status == CitationReviewStatus.MANUAL_CONFIRMED,
                MonitoringCitation.domain.is_not(None),
            )
            .distinct()
        ).all()
        if domain
    }

    per_batch: dict[uuid.UUID, dict] = {
        batch.id: {
            "batch_id": str(batch.id),
            "name": batch.name,
            "status": batch.status.value,
            "task_count": batch.task_count,
            "item_count": batch.item_count,
            "created_at": batch.created_at,
            "dispatched_at": batch.dispatched_at,
            "channels": {},
            "task_states": {},
            "with_receipt": 0,
            "reachable": 0,
            "visibility_checked": 0,
            "visibility_matched": 0,
            "cited": 0,
        }
        for batch in batch_rows
    }

    for batch_id, task_id, status, channel_name in tasks:
        row = per_batch.get(batch_id)
        if row is None:
            continue
        state = status.value if hasattr(status, "value") else str(status)
        row["task_states"][state] = row["task_states"].get(state, 0) + 1
        if channel_name:
            row["channels"][channel_name] = row["channels"].get(channel_name, 0) + 1
        receipt = receipts.get(task_id)
        if receipt is None:
            continue
        row["with_receipt"] += 1
        check = checks.get(str(receipt.id))
        if check is not None:
            row["visibility_checked"] += 1
            if check["matched"]:
                row["visibility_matched"] += 1
        if receipt.last_reachable is True:
            row["reachable"] += 1
        host = host_of(receipt.published_url)
        if host and host in cited_domains:
            row["cited"] += 1

    items = []
    for row in per_batch.values():
        tasks_total = sum(row["task_states"].values())
        if tasks_total == 0 and row["task_count"] == 0:
            stage = "not_dispatched"  # 预检过但没确认投喂，或确认后未生成任务
        elif row["with_receipt"] == 0:
            stage = "no_receipt"
        elif row["visibility_checked"] == 0:
            stage = "no_visibility_check"
        elif row["cited"] == 0:
            stage = "not_cited"
        else:
            stage = "cited"
        row["tasks_total"] = tasks_total
        row["stage"] = stage
        row["receipt_rate"] = (
            round(row["with_receipt"] / tasks_total, 4) if tasks_total else None
        )
        items.append(row)

    return {
        "items": items,
        "summary": {
            "batches": len(items),
            "tasks": sum(item["tasks_total"] for item in items),
            "receipts": sum(item["with_receipt"] for item in items),
            "cited": sum(item["cited"] for item in items),
            "not_dispatched": sum(1 for item in items if item["stage"] == "not_dispatched"),
        },
        "caveats": [
            "手工建单的发布任务不归属任何批次，不在本视图内。",
            "「已回执」「已收录」「已被引用」是三个独立观测，不能相乘当成整体成功率。",
            "已被引用只统计人工复核通过的引用。",
        ],
    }
