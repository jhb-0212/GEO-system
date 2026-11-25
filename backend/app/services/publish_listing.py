"""发布列表的口径层：任务、回执的分页与关联读取。

为什么下沉：
发布页（`api/publishing.py`）和回链看板（`services/publish_board.py`）都在读同一批
`publish_tasks / publish_receipts / channels`，而且都在给「一张回执属于哪个任务、
哪个渠道、挂了哪个预算」做 join。两份 join 各自演化的结果是：看板说「已回执 12 条」，
发布页说「回执 9 条」，谁也不知道差的那 3 条是什么。

这里只做**读**，不改任何状态：
- 「转人工原因」取该任务最新一条带 handoff 错误码的尝试记录，同一任务只认最新一条；
- 一张任务可能有多条回执，列表里取最近一条（`received_at desc, id desc`）作为展示值，
  完整链路仍以回执列表接口为准。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    BudgetApproval,
    Channel,
    ContentItem,
    ContentReview,
    ContentVersion,
    OAuthConnection,
    PublishAccount,
    PublishAttempt,
    PublishReceipt,
    PublishTask,
)
from app.models.enums import ContentFormat, PublishHandoffReason, PublishTaskStatus

# 转人工原因集合：与 PublishHandoffReason 保持单一来源，不在 api 里另抄一份。
HANDOFF_ERROR_CODES = {reason.value for reason in PublishHandoffReason}


def handoff_lookup(
    db: Session, project_id: uuid.UUID, task_ids: list[uuid.UUID]
) -> dict[uuid.UUID, PublishAttempt]:
    """每个任务最新一条「带转人工原因」的尝试记录。"""
    if not task_ids:
        return {}
    result: dict[uuid.UUID, PublishAttempt] = {}
    for attempt in db.scalars(
        select(PublishAttempt)
        .where(
            PublishAttempt.project_id == project_id,
            PublishAttempt.task_id.in_(task_ids),
            PublishAttempt.error_code.in_(HANDOFF_ERROR_CODES),
        )
        .order_by(PublishAttempt.attempt_no.desc(), PublishAttempt.id.desc())
    ).all():
        result.setdefault(attempt.task_id, attempt)
    return result


def receipt_lookup(
    db: Session, project_id: uuid.UUID, task_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[PublishReceipt, str | None]]:
    """每个任务最近一条回执（含预算标题）。"""
    if not task_ids:
        return {}
    result: dict[uuid.UUID, tuple[PublishReceipt, str | None]] = {}
    for receipt, budget_title in db.execute(
        select(PublishReceipt, BudgetApproval.title)
        .outerjoin(BudgetApproval, BudgetApproval.id == PublishReceipt.budget_approval_id)
        .where(
            PublishReceipt.project_id == project_id,
            PublishReceipt.task_id.in_(task_ids),
        )
        .order_by(PublishReceipt.received_at.desc(), PublishReceipt.id.desc())
    ).all():
        result.setdefault(receipt.task_id, (receipt, budget_title))
    return result


def _task_row_payload(
    row: PublishTask,
    version_no: int | None,
    version_title: str | None,
    account_id: uuid.UUID | None,
    account_name: str | None,
    receipt: tuple[PublishReceipt, str | None] | None,
    handoff: PublishAttempt | None,
) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "serial_no": row.serial_no,
        "status": row.status,
        "publish_mode": row.publish_mode.value,
        "handoff_reason": handoff.error_code if handoff else None,
        "handoff_note": handoff.error_note if handoff else None,
        "channel_id": str(row.channel_id),
        "account_id": str(account_id) if account_id else None,
        "account_name": account_name,
        "version_id": str(row.version_id),
        "version_no": version_no,
        "version_title": version_title,
        "trace_id": row.trace_id,
        "source_batch_id": str(row.source_batch_id) if row.source_batch_id else None,
        "receipt_id": str(receipt[0].id) if receipt else None,
        "published_url": receipt[0].published_url if receipt else None,
        "received_at": receipt[0].received_at if receipt else None,
        "budget_approval_id": (
            str(receipt[0].budget_approval_id)
            if receipt and receipt[0].budget_approval_id
            else None
        ),
        "budget_title": receipt[1] if receipt else None,
    }


def page_tasks(
    db: Session,
    project_id: uuid.UUID,
    *,
    status: PublishTaskStatus | None = None,
    content_type: ContentFormat | None = None,
    within_days: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[dict[str, Any]]]:
    filters = [PublishTask.project_id == project_id]
    if status is not None:
        filters.append(PublishTask.status == status)
    if content_type is not None:
        filters.append(ContentItem.content_type == content_type)
    if within_days is not None:
        filters.append(
            PublishTask.created_at
            >= datetime.now(timezone.utc) - timedelta(days=within_days)
        )

    total = int(
        db.scalar(
            select(func.count())
            .select_from(PublishTask)
            .join(ContentVersion, ContentVersion.id == PublishTask.version_id)
            .join(ContentItem, ContentItem.id == ContentVersion.item_id)
            .where(*filters)
        )
        or 0
    )
    rows = db.execute(
        select(
            PublishTask,
            ContentVersion.version_no,
            ContentItem.title,
            PublishAccount.id,
            PublishAccount.account_name,
        )
        .join(ContentVersion, ContentVersion.id == PublishTask.version_id)
        .join(ContentItem, ContentItem.id == ContentVersion.item_id)
        .outerjoin(PublishAccount, PublishAccount.id == PublishTask.account_id)
        .where(*filters)
        .order_by(PublishTask.created_at.desc(), PublishTask.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    task_ids = [row.id for row, *_ in rows]
    receipts = receipt_lookup(db, project_id, task_ids)
    handoffs = handoff_lookup(db, project_id, task_ids)
    payloads = [
        _task_row_payload(
            row, version_no, version_title, account_id, account_name,
            receipts.get(row.id), handoffs.get(row.id),
        )
        for row, version_no, version_title, account_id, account_name in rows
    ]
    return total, payloads


def receipt_filters(
    project_id: uuid.UUID,
    *,
    channel_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    has_budget: bool | None = None,
    has_page_approval: bool | None = None,
    q: str | None = None,
) -> tuple[list, list]:
    """回执列表的过滤条件；渠道过滤落在任务上，其余落在回执上。"""
    filters = [PublishReceipt.project_id == project_id]
    task_filters = [PublishTask.project_id == project_id]
    if channel_id is not None:
        task_filters.append(PublishTask.channel_id == channel_id)
    if task_id is not None:
        filters.append(PublishReceipt.task_id == task_id)
    if has_budget is True:
        filters.append(PublishReceipt.budget_approval_id.is_not(None))
    elif has_budget is False:
        filters.append(PublishReceipt.budget_approval_id.is_(None))
    if has_page_approval is True:
        filters.append(PublishReceipt.page_approval_id.is_not(None))
    elif has_page_approval is False:
        filters.append(PublishReceipt.page_approval_id.is_(None))
    if q and q.strip():
        filters.append(PublishReceipt.published_url.ilike(f"%{q.strip()}%"))
    return filters, task_filters


def page_receipts(
    db: Session,
    project_id: uuid.UUID,
    *,
    channel_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    has_budget: bool | None = None,
    has_page_approval: bool | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[dict[str, Any]]]:
    filters, task_filters = receipt_filters(
        project_id,
        channel_id=channel_id,
        task_id=task_id,
        has_budget=has_budget,
        has_page_approval=has_page_approval,
        q=q,
    )
    total = int(
        db.scalar(
            select(func.count())
            .select_from(PublishReceipt)
            .join(PublishTask, PublishTask.id == PublishReceipt.task_id)
            .where(*filters, *task_filters)
        )
        or 0
    )
    rows = db.execute(
        select(
            PublishReceipt,
            PublishTask.serial_no,
            PublishTask.channel_id,
            Channel.name,
            BudgetApproval.title,
        )
        .join(PublishTask, PublishTask.id == PublishReceipt.task_id)
        .outerjoin(Channel, Channel.id == PublishTask.channel_id)
        .outerjoin(BudgetApproval, BudgetApproval.id == PublishReceipt.budget_approval_id)
        .where(*filters, *task_filters)
        .order_by(PublishReceipt.received_at.desc(), PublishReceipt.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    payloads = [
        {
            "id": str(receipt.id),
            "task_id": str(receipt.task_id),
            "serial_no": serial_no,
            "channel_id": str(channel_id_value),
            "channel_name": channel_name,
            "published_url": receipt.published_url,
            "page_approval_id": str(receipt.page_approval_id) if receipt.page_approval_id else None,
            "received_at": receipt.received_at,
            "verified_at": receipt.verified_at,
            "budget_approval_id": (
                str(receipt.budget_approval_id) if receipt.budget_approval_id else None
            ),
            "budget_title": budget_title,
        }
        for receipt, serial_no, channel_id_value, channel_name, budget_title in rows
    ]
    return total, payloads


def account_task_counts(
    db: Session, project_id: uuid.UUID, account_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """每个发布账号名下的任务数（列表页展示用，不是统计口径）。"""
    if not account_ids:
        return {}
    rows = db.execute(
        select(PublishTask.account_id, func.count())
        .where(
            PublishTask.project_id == project_id,
            PublishTask.account_id.in_(account_ids),
        )
        .group_by(PublishTask.account_id)
    ).all()
    return {account_id: int(count) for account_id, count in rows}


def connections_for(
    db: Session, connection_ids: list[uuid.UUID]
) -> dict[uuid.UUID, OAuthConnection]:
    if not connection_ids:
        return {}
    rows = db.scalars(
        select(OAuthConnection).where(OAuthConnection.id.in_(connection_ids))
    ).all()
    return {row.id: row for row in rows}


def account_payload(
    account: PublishAccount,
    *,
    task_count: int = 0,
    connection: OAuthConnection | None = None,
) -> dict[str, Any]:
    """发布账号的展示形态（列表、创建、更新三处共用）。"""
    return {
        "id": str(account.id),
        "account_name": account.account_name,
        "channel_id": str(account.channel_id),
        "is_active": account.is_active,
        "notes": account.notes,
        "task_count": int(task_count),
        "oauth_connection_id": (
            str(account.oauth_connection_id) if account.oauth_connection_id else None
        ),
        "oauth_status": connection.status.value if connection else None,
        "oauth_provider_code": connection.provider_code if connection else None,
        "oauth_external_account_name": (
            connection.external_account_name if connection else None
        ),
    }


def page_accounts(
    db: Session,
    project_id: uuid.UUID,
    *,
    channel_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[dict[str, Any]]]:
    filters = [PublishAccount.project_id == project_id]
    if channel_id is not None:
        filters.append(PublishAccount.channel_id == channel_id)

    total = int(db.scalar(select(func.count()).select_from(PublishAccount).where(*filters)) or 0)
    rows = db.scalars(
        select(PublishAccount)
        .where(*filters)
        .order_by(PublishAccount.account_name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    task_counts = account_task_counts(db, project_id, [row.id for row in rows])
    connections = connections_for(
        db, [row.oauth_connection_id for row in rows if row.oauth_connection_id]
    )
    payloads = [
        account_payload(
            row,
            task_count=task_counts.get(row.id, 0),
            connection=connections.get(row.oauth_connection_id),
        )
        for row in rows
    ]
    return total, payloads


# --- 发布链路里的单行读：账号/渠道/审批快照/尝试序号/幂等键 ---


def account_bound_to_oauth(
    db: Session,
    project_id: uuid.UUID,
    connection_id: uuid.UUID | None,
    *,
    exclude_account_id: uuid.UUID | None = None,
) -> bool:
    """一个 OAuth 连接只能绑一个发布账号。"""
    if connection_id is None:
        return False
    query = select(PublishAccount).where(
        PublishAccount.project_id == project_id,
        PublishAccount.oauth_connection_id == connection_id,
    )
    if exclude_account_id is not None:
        query = query.where(PublishAccount.id != exclude_account_id)
    return db.scalar(query) is not None


def account_name_exists(
    db: Session, project_id: uuid.UUID, channel_id: uuid.UUID, account_name: str
) -> bool:
    return (
        db.scalar(
            select(PublishAccount).where(
                PublishAccount.project_id == project_id,
                PublishAccount.channel_id == channel_id,
                PublishAccount.account_name == account_name,
            )
        )
        is not None
    )


def account_task_count(db: Session, project_id: uuid.UUID, account_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(PublishTask)
            .where(
                PublishTask.project_id == project_id,
                PublishTask.account_id == account_id,
            )
        )
        or 0
    )


def channel_row(
    db: Session, project_id: uuid.UUID, channel_id: uuid.UUID
) -> Channel | None:
    return db.scalar(
        select(Channel).where(
            Channel.project_id == project_id,
            Channel.id == channel_id,
        )
    )


def channel_name(db: Session, channel_id: uuid.UUID) -> str | None:
    return db.scalar(select(Channel.name).where(Channel.id == channel_id))


def latest_content_review(db: Session, version_id: uuid.UUID) -> ContentReview | None:
    return db.scalar(
        select(ContentReview)
        .where(ContentReview.version_id == version_id)
        .order_by(ContentReview.created_at.desc(), ContentReview.id.desc())
    )


def next_attempt_no(db: Session, task_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.max(PublishAttempt.attempt_no)).where(
                PublishAttempt.task_id == task_id
            )
        )
        or 0
    ) + 1


def task_by_idempotency(
    db: Session, project_id: uuid.UUID, idempotency_key: str
) -> PublishTask | None:
    return db.scalar(
        select(PublishTask).where(
            PublishTask.project_id == project_id,
            PublishTask.idempotency_key == idempotency_key,
        )
    )


def latest_handoff_attempt(
    db: Session, project_id: uuid.UUID, task_id: uuid.UUID
) -> PublishAttempt | None:
    return db.scalar(
        select(PublishAttempt)
        .where(
            PublishAttempt.project_id == project_id,
            PublishAttempt.task_id == task_id,
            PublishAttempt.error_code.in_(HANDOFF_ERROR_CODES),
        )
        .order_by(PublishAttempt.attempt_no.desc(), PublishAttempt.id.desc())
    )
