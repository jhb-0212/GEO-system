"""投喂批次 → 发布任务：批次是计划，任务是执行。

为什么必须有这一层：
- 闭环看板（`services/publish_closure.py`）以发布任务为轴串任务→回执→收录→引用；
- 新鲜度（`services/content_freshness.py`）只认 `publish_receipts.received_at`；
- 收录检测（`services/publish_visibility.py`）只认回执上的真实 URL。

所以「把批次标成已投喂」这件事如果不同时生成任务，这批内容就同时从三条链路里消失：
既不算已发布，也不进「断在哪一环」，还不算过期未更新——永久沉默。

本模块只负责「把计划落成任务」，不负责真的发出去：
- 任务状态一律 `pending`，等执行岗在发布页执行；
- 批次状态推进到 `dispatched` 的语义是「计划已确认、任务已入队」，不等于「已被 AI 平台收录」；
- 确认时冻结 `approval_snapshot`，事后可解释「当时这些渠道是准入的、用的是哪个账号」。

取消/回滚交给发布侧既有能力：任务可 `publish.cancel` 取消，批次不复制一套撤回逻辑。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import (
    Channel,
    ContentItem,
    ContentVersion,
    DistributionBatch,
    DistributionBatchItem,
    PublishAccount,
    PublishTask,
)
from app.models.enums import (
    ChannelApprovalStatus,
    ContentKind,
    ContentStatus,
    DistributionBatchStatus,
    PublishTaskStatus,
)
from app.services.content_status import mark_version_status
from app.services.publish_task_keys import idempotency_key
from app.services.state_machine import ensure_distribution_transition
from app.services.trace_chain import trace_for_content_version


@dataclass
class PlanResult:
    created: list[uuid.UUID] = field(default_factory=list)
    reused: list[uuid.UUID] = field(default_factory=list)
    task_keys: list[str] = field(default_factory=list)
    approval_snapshot: dict = field(default_factory=dict)

    @property
    def task_count(self) -> int:
        return len(self.created) + len(self.reused)


def _parse_uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _approved_channels(db: Session, project_id: uuid.UUID, channel_ids: list) -> list[Channel]:
    parsed = [item for item in (_parse_uuid(value) for value in channel_ids) if item]
    if not parsed:
        raise AppError("批次没有可用的目标渠道", code="batch_no_channel")
    rows = db.scalars(
        select(Channel).where(Channel.id.in_(parsed), Channel.project_id == project_id)
    ).all()
    found = {row.id for row in rows}
    missing = [channel_id for channel_id in parsed if channel_id not in found]
    if missing:
        raise AppError(
            f"{len(missing)} 个目标渠道不属于当前项目或已删除",
            code="batch_channel_not_approved",
        )
    not_ready = [
        row.name for row in rows
        if row.approval_status != ChannelApprovalStatus.APPROVED or not row.is_active
    ]
    if not_ready:
        raise AppError(
            f"渠道未准入或已停用：{'、'.join(not_ready[:5])}",
            code="batch_channel_not_approved",
        )
    return list(rows)


def _account_by_channel(db: Session, project_id: uuid.UUID, channels: list[Channel]) -> dict[uuid.UUID, PublishAccount]:
    """每条目标渠道必须有一个启用中的发布账号，否则任务建不出来。

    多个账号时取最早创建的那个：同一渠道重复配账号属于配置冗余，不由本模块替用户挑新账号。
    """
    rows = db.scalars(
        select(PublishAccount)
        .where(
            PublishAccount.project_id == project_id,
            PublishAccount.channel_id.in_([channel.id for channel in channels]),
            PublishAccount.is_active.is_(True),
        )
        .order_by(PublishAccount.created_at.asc())
    ).all()
    accounts: dict[uuid.UUID, PublishAccount] = {}
    for row in rows:
        accounts.setdefault(row.channel_id, row)
    missing = [channel.name for channel in channels if channel.id not in accounts]
    if missing:
        raise AppError(
            f"渠道还没有启用中的发布账号：{'、'.join(missing[:5])}；先到发布页配置账号再确认投喂",
            code="batch_channel_no_account",
        )
    return accounts


def _channel_versions(
    db: Session, project_id: uuid.UUID, items: list[DistributionBatchItem]
) -> list[ContentVersion]:
    """只允许渠道稿、且只允许当前版本。

    - 母稿（master）没有渠道账号可发，建任务会被发布侧拒绝，所以这里先挡住；
    - 版本被新版本替代后不能再发出去（与手工建单同一口径），
      `current_version_id` 为空的历史数据不做强制，避免误伤老数据。
    """
    version_ids = [item.content_version_id for item in items]
    if not version_ids:
        raise AppError("批次里没有内容版本", code="batch_empty")
    rows = db.execute(
        select(ContentVersion, ContentItem)
        .join(ContentItem, ContentItem.id == ContentVersion.item_id)
        .where(
            ContentVersion.project_id == project_id,
            ContentVersion.id.in_(version_ids),
        )
    ).all()
    by_id = {version.id: (version, item) for version, item in rows}
    missing = [version_id for version_id in version_ids if version_id not in by_id]
    if missing:
        raise AppError("批次内有内容版本不属于当前项目", code="batch_version_not_found")
    not_channel = [
        item.title for version, item in by_id.values() if item.kind != ContentKind.CHANNEL
    ]
    if not_channel:
        raise AppError(
            f"只有渠道稿能生成发布任务，以下内容仍是母稿：{'、'.join(not_channel[:5])}",
            code="batch_content_not_channel",
        )
    replaced = [
        item.title
        for version, item in by_id.values()
        if item.current_version_id is not None and item.current_version_id != version.id
    ]
    if replaced:
        raise AppError(
            f"以下内容已被新版本替代，不能再投喂：{'、'.join(replaced[:5])}",
            code="batch_version_replaced",
        )
    return [version for version, _ in by_id.values()]


def _precheck_hash(precheck: dict | None) -> str | None:
    if not precheck:
        return None
    canonical = json.dumps(precheck, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def plan_tasks(
    db: Session,
    *,
    project_id: uuid.UUID,
    batch: DistributionBatch,
    items: list[DistributionBatchItem],
    actor_id: uuid.UUID | None,
    precheck: dict | None = None,
) -> PlanResult:
    """把已通过预检的批次按「内容版本 × 目标渠道」落成发布任务。

    幂等：任务键由批次推导（`batch-<批次id前12位>`），同一批次重复调用只会复用既有任务，
    不会因为点两次按钮多发一轮。真正重复投喂要新建批次——那是另一个业务意图。
    """
    channels = _approved_channels(db, project_id, list(batch.target_channel_ids or []))
    accounts = _account_by_channel(db, project_id, channels)
    versions = _channel_versions(db, project_id, items)

    task_key = f"batch-{batch.id.hex[:12]}"
    result = PlanResult()
    for version in versions:
        trace_id = trace_for_content_version(db, version.id)
        for channel in channels:
            account = accounts[channel.id]
            key = idempotency_key(account.id, channel.id, version.id, task_key)
            existing = db.scalar(
                select(PublishTask).where(
                    PublishTask.project_id == project_id,
                    PublishTask.idempotency_key == key,
                )
            )
            if existing is not None:
                result.reused.append(existing.id)
                continue
            task = PublishTask(
                project_id=project_id,
                version_id=version.id,
                channel_id=channel.id,
                account_id=account.id,
                task_key=task_key,
                idempotency_key=key,
                status=PublishTaskStatus.PENDING,
                trace_id=trace_id,
                source_batch_id=batch.id,
                created_by=actor_id,
            )
            db.add(task)
            db.flush()
            result.created.append(task.id)
            # 建单即视为已排期；published 必须等回执。
            if version.status == ContentStatus.APPROVED:
                mark_version_status(db, version, ContentStatus.PENDING_PUBLISH)
    result.task_keys = [task_key]

    snapshot_at = datetime.now(timezone.utc)
    result.approval_snapshot = {
        "snapshot_at": snapshot_at.isoformat(),
        "batch_id": str(batch.id),
        "task_key": task_key,
        "precheck_hash": _precheck_hash(precheck if precheck is not None else batch.precheck),
        "channels": [
            {
                "id": str(channel.id),
                "name": channel.name,
                "approval_status": channel.approval_status.value,
                "is_active": channel.is_active,
            }
            for channel in channels
        ],
        "accounts": [
            {
                "channel_id": str(account.channel_id),
                "account_id": str(account.id),
                "account_name": account.account_name,
            }
            for account in accounts.values()
        ],
        "versions": [
            {"id": str(version.id), "status": version.status.value, "content_hash": version.content_hash}
            for version in versions
        ],
    }
    return result


def apply_plan(
    db: Session,
    *,
    project_id: uuid.UUID,
    batch: DistributionBatch,
    items: list[DistributionBatchItem],
    actor_id: uuid.UUID | None,
    precheck: dict | None = None,
) -> PlanResult:
    """落成任务并把批次推进到 dispatched，同时写入准入快照与任务数。

    只做 flush，不 commit：事务边界留在 api，和审计写在同一个事务里。
    """
    result = plan_tasks(
        db,
        project_id=project_id,
        batch=batch,
        items=items,
        actor_id=actor_id,
        precheck=precheck,
    )
    ensure_distribution_transition(batch.status, DistributionBatchStatus.DISPATCHED)
    batch.status = DistributionBatchStatus.DISPATCHED
    batch.task_count = result.task_count
    if batch.approval_snapshot is None:
        batch.approval_snapshot = result.approval_snapshot
    batch.dispatched_at = datetime.now(timezone.utc)
    batch.dispatched_by = actor_id
    return result
