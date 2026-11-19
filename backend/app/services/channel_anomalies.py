"""渠道台账与发布回执的一致性检查。

只读、不修改业务数据。目标是让“渠道状态、发布任务、回执 URL”之间的不一致
在看板上可见，而不是等人工逐条点开才发现。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Channel, PublishReceipt, PublishTask
from app.models.enums import ChannelStatus, PublishTaskStatus


def _anomaly(
    *,
    code: str,
    severity: str,
    channel: Channel,
    message: str,
    recommended_action: str,
    task: PublishTask | None = None,
    receipt: PublishReceipt | None = None,
) -> dict:
    return {
        "code": code,
        "severity": severity,
        "channel_id": str(channel.id),
        "channel_code": channel.code,
        "channel_name": channel.name,
        "channel_status": str(channel.status),
        "task_id": str(task.id) if task is not None else None,
        "task_status": str(task.status) if task is not None else None,
        "receipt_id": str(receipt.id) if receipt is not None else None,
        "published_url": receipt.published_url if receipt is not None else None,
        "message": message,
        "recommended_action": recommended_action,
        "task_updated_at": task.updated_at if task is not None else None,
        "receipt_received_at": receipt.received_at if receipt is not None else None,
    }


def detect_channel_anomalies(db: Session, project_id: uuid.UUID) -> dict:
    """返回当前项目需要人工处理的渠道/发布异常。

    规则刻意保持少量、可解释：
    1. 回执存在但任务不是 published；
    2. 任务 published 但没有回执；
    3. 任务 published 且有回执，但渠道状态不是 published；
    4. 任务 unknown（请求可能已发出，禁止盲目重发）；
    5. 渠道标 published，但整个渠道没有任何回执；
    6. 同一任务出现多条回执。
    """
    rows = db.execute(
        select(PublishTask, Channel, PublishReceipt)
        .join(Channel, PublishTask.channel_id == Channel.id)
        .outerjoin(PublishReceipt, PublishReceipt.task_id == PublishTask.id)
        .where(
            PublishTask.project_id == project_id,
            Channel.project_id == project_id,
        )
        .order_by(Channel.code, PublishTask.created_at, PublishReceipt.received_at)
    ).all()

    grouped: dict[uuid.UUID, dict] = {}
    for task, channel, receipt in rows:
        item = grouped.setdefault(
            task.id,
            {"task": task, "channel": channel, "receipts": []},
        )
        if receipt is not None:
            item["receipts"].append(receipt)

    anomalies: list[dict] = []
    receipted_channels: set[uuid.UUID] = set()
    for item in grouped.values():
        task: PublishTask = item["task"]
        channel: Channel = item["channel"]
        receipts: list[PublishReceipt] = item["receipts"]
        if receipts:
            receipted_channels.add(channel.id)

        if task.status == PublishTaskStatus.UNKNOWN:
            anomalies.append(
                _anomaly(
                    code="publish_task_unknown",
                    severity="high",
                    channel=channel,
                    task=task,
                    receipt=receipts[0] if receipts else None,
                    message="发布任务处于 unknown，外部请求可能已发出但结果未确认。",
                    recommended_action="先人工核实平台是否已发布，禁止直接重发；确认后补回执或回退状态。",
                )
            )

        if task.status == PublishTaskStatus.PUBLISHED and not receipts:
            anomalies.append(
                _anomaly(
                    code="published_task_missing_receipt",
                    severity="high",
                    channel=channel,
                    task=task,
                    message="任务标记为 published，但没有发布回执 URL。",
                    recommended_action="补录真实发布 URL 和回执；没有真实回执时不得按已发布结案。",
                )
            )

        if receipts and task.status != PublishTaskStatus.PUBLISHED:
            anomalies.append(
                _anomaly(
                    code="receipt_status_mismatch",
                    severity="high",
                    channel=channel,
                    task=task,
                    receipt=receipts[0],
                    message=f"已有回执，但任务状态是 {task.status.value}，不是 published。",
                    recommended_action="核对回执是否属于该任务；确认后把任务改为 published 或撤回错误回执。",
                )
            )

        if (
            task.status == PublishTaskStatus.PUBLISHED
            and receipts
            and channel.status != ChannelStatus.PUBLISHED
        ):
            anomalies.append(
                _anomaly(
                    code="channel_status_mismatch",
                    severity="warning",
                    channel=channel,
                    task=task,
                    receipt=receipts[0],
                    message=(
                        f"渠道状态是 {channel.status.value}，但已有 published 任务和回执；"
                        "渠道台账与发布记录不一致。"
                    ),
                    recommended_action="确认该回执是否为真实发布：是则把渠道状态改为 published；测试回执则改任务状态并说明。",
                )
            )

        if len(receipts) > 1:
            anomalies.append(
                _anomaly(
                    code="duplicate_receipts",
                    severity="warning",
                    channel=channel,
                    task=task,
                    receipt=receipts[0],
                    message=f"同一任务有 {len(receipts)} 条回执，存在重复登记。",
                    recommended_action="核对哪条是真实上线 URL，保留一条主回执并说明其余记录。",
                )
            )

    # 渠道自身标 published，但从未登记过任何回执：台账状态没有闭环证据。
    # 这里只遍历有发布任务的渠道；完全没有任何任务的历史渠道不应被误报。
    published_channels = {
        item["channel"].id: item["channel"]
        for item in grouped.values()
        if item["channel"].status == ChannelStatus.PUBLISHED
    }
    for channel in published_channels.values():
        if channel.id not in receipted_channels:
            anomalies.append(
                _anomaly(
                    code="published_channel_without_receipt",
                    severity="warning",
                    channel=channel,
                    message="渠道标记为 published，但没有任何发布回执。",
                    recommended_action="补录至少一条回执，或把渠道状态降为 candidate/observed。",
                )
            )

    high = sum(1 for row in anomalies if row["severity"] == "high")
    warning = sum(1 for row in anomalies if row["severity"] == "warning")
    return {
        "generated_at": datetime.now(timezone.utc),
        "counts": {"total": len(anomalies), "high": high, "warning": warning},
        "anomalies": anomalies,
    }
