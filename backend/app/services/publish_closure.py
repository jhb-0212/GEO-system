"""发布闭环看板：以「发布任务」为轴，把 任务 → 回执 → 收录 → 被引用 四段串起来。

与「发布回链」的区别：回链看板以回执为轴（没有回执的单子根本看不见），
这里以任务为轴，能直接看出**断在哪一环**——是任务没发出、发出去没回执、
有回执没检测、检测失败、没进索引，还是进了索引但 AI 没引用。

口径沿用回链看板：被引用只认人工复核通过的引用；检测失败停在「未查成」，
不并入「未收录」；不参与归因。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Channel,
    ContentItem,
    ContentVersion,
    MonitoringCitation,
    PublishReceipt,
    PublishTask,
)
from app.models.enums import CitationReviewStatus, PublishTaskStatus
from app.services.publish_board import host_of
from app.services.publish_visibility import latest_checks

STAGE_LABEL = {
    "no_receipt": "缺回执",
    "not_checked": "未做收录检测",
    "check_failed": "检测失败",
    "not_in_index": "未被收录",
    "not_cited": "未被引用",
    "closed": "闭环",
    "task_closed": "任务终止",
    "not_published": "尚未发布",
}

STAGE_HINT = {
    "no_receipt": "任务已建但没收到回执：先确认是否真的发出，别重复发。",
    "not_checked": "有回执没检测记录：先跑收录检测再判断渠道效果。",
    "check_failed": "检测调用失败，结论未知：重试检测，不要把失败当未收录。",
    "not_in_index": "已检测但页面没进搜索结果：先看索引与站点过滤，再谈内容质量。",
    "not_cited": "已被收录但 AI 没引用：问题在内容与信源权威度，不在收录。",
    "closed": "已被检索并被 AI 引用，链路完整。",
    "task_closed": "任务已失败或取消，链路提前结束。",
    "not_published": "任务尚未执行，还没进入链路。",
}


def stage_of(
    task_status: PublishTaskStatus,
    has_receipt: bool,
    check: dict | None,
    cited: bool,
) -> str:
    """判定链路断点：纯函数，便于单元测试逐条覆盖，不依赖库里有没有样本。"""
    if not has_receipt:
        if task_status in (PublishTaskStatus.FAILED, PublishTaskStatus.CANCELLED):
            return "task_closed"
        if task_status == PublishTaskStatus.PENDING:
            return "not_published"
        return "no_receipt"
    if check is None:
        return "not_checked"
    if check["error_code"]:
        return "check_failed"
    if not check["matched"]:
        return "not_in_index"
    if not cited:
        return "not_cited"
    return "closed"


def closure(db: Session, project_id: uuid.UUID, *, limit: int = 200) -> dict:
    rows = db.execute(
        select(
            PublishTask,
            Channel.name.label("channel_name"),
            ContentItem.title.label("content_title"),
        )
        .join(ContentVersion, ContentVersion.id == PublishTask.version_id)
        .join(ContentItem, ContentItem.id == ContentVersion.item_id)
        .outerjoin(Channel, Channel.id == PublishTask.channel_id)
        .where(PublishTask.project_id == project_id)
        .order_by(PublishTask.serial_no.desc())
        .limit(limit)
    ).all()

    task_ids = [task.id for task, _, _ in rows]
    receipts = (
        list(db.scalars(select(PublishReceipt).where(PublishReceipt.task_id.in_(task_ids))).all())
        if task_ids
        else []
    )
    latest_receipt: dict[uuid.UUID, PublishReceipt] = {}
    for receipt in receipts:
        current = latest_receipt.get(receipt.task_id)
        if current is None or receipt.received_at > current.received_at:
            latest_receipt[receipt.task_id] = receipt

    checks = {row["receipt_id"]: row for row in latest_checks(db, project_id, limit=limit * 2)} if receipts else {}
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

    items = []
    for task, channel_name, content_title in rows:
        receipt = latest_receipt.get(task.id)
        check = checks.get(str(receipt.id)) if receipt else None
        host = host_of(receipt.published_url) if receipt else ""
        cited = bool(host) and host in cited_domains

        if receipt is None:
            stage = stage_of(task.status, False, None, False)
        else:
            stage = stage_of(task.status, True, check, cited)

        items.append(
            {
                "task_id": str(task.id),
                "serial_no": task.serial_no,
                "task_status": task.status.value,
                "channel_name": channel_name,
                "content_title": content_title,
                "scheduled_at": task.scheduled_at,
                "receipt_id": str(receipt.id) if receipt else None,
                "published_url": receipt.published_url if receipt else None,
                "published_host": host or None,
                "received_at": receipt.received_at if receipt else None,
                "visibility_checked_at": check["checked_at"] if check else None,
                "visibility_matched": bool(check["matched"]) if check else None,
                "visibility_error_code": check["error_code"] if check else None,
                "cited": cited,
                "stage": stage,
                "stage_label": STAGE_LABEL[stage],
                "hint": STAGE_HINT[stage],
            }
        )

    counts = {stage: 0 for stage in STAGE_LABEL}
    for item in items:
        counts[item["stage"]] += 1

    with_receipt = sum(1 for item in items if item["receipt_id"])
    return {
        "items": items,
        "counts": counts,
        "summary": {
            "total_tasks": len(items),
            "tasks_with_receipt": with_receipt,
            "closed": counts["closed"],
            # 分母口径：闭环率只算已经拿到回执的任务，没回执的单子不参与
            "closure_rate": round(counts["closed"] / with_receipt, 4) if with_receipt else None,
            "broken_before_receipt": sum(1 for item in items if item["stage"] in ("no_receipt", "task_closed")),
            "broken_after_receipt": sum(1 for item in items if item["stage"] in ("not_checked", "check_failed", "not_in_index", "not_cited")),
        },
        "caveats": [
            "「被引用」只统计人工复核通过的引用，未复核与已驳回不算。",
            "闭环率的分母是「已拿到回执的任务」，没回执的任务不进分母。",
            "检测失败停在「检测失败」，不并入「未被收录」。",
        ],
    }
