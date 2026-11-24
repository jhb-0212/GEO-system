"""预算审批的读取口径：列表页的关联聚合与详情快照。

`api/budget_approvals.py` 只留校验、状态迁移与审计；这里负责：

- `user_names`：申请人/审批人姓名批量取回（一次查询，不在循环里查）；
- `list_related`：媒体报价、渠道名、已挂回执数三张关联一次取齐；
- `load_detail`：单条详情（报价 + 渠道名 + 回执明细 + 挂载数）；
- `page_rows`：列表分页。
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    BudgetApproval,
    Channel,
    MediaQuote,
    PublishReceipt,
    User,
)


def user_names(db: Session, rows: list[BudgetApproval]) -> dict:
    user_ids = {row.requested_by for row in rows if row.requested_by}
    user_ids |= {row.approved_by for row in rows if row.approved_by}
    if not user_ids:
        return {}
    return {
        user_id: display_name or username
        for user_id, display_name, username in db.execute(
            select(User.id, User.display_name, User.username).where(User.id.in_(user_ids))
        ).all()
    }


def quote_payload(quote: MediaQuote | None, channel_name: str | None) -> dict | None:
    if quote is None:
        return None
    return {
        "id": str(quote.id),
        "channel_id": str(quote.channel_id) if quote.channel_id else None,
        "channel_name": channel_name,
        "unit_price": float(quote.unit_price),
        "quantity": quote.quantity,
        "currency": quote.currency,
        "status": quote.status.value,
        "approved_at": quote.approved_at,
    }


def serialize(
    row: BudgetApproval,
    names: dict | None = None,
    *,
    quote: MediaQuote | None = None,
    channel_name: str | None = None,
    linked_count: int = 0,
    receipts: list[PublishReceipt] | None = None,
) -> dict:
    names = names or {}
    receipts = receipts or []
    total_quantity = float(row.quantity) if row.quantity is not None else None
    remaining = (
        max(total_quantity - linked_count, 0) if total_quantity is not None else None
    )
    return {
        "id": str(row.id),
        "category": row.category.value if hasattr(row.category, "value") else row.category,
        "title": row.title,
        "quantity": total_quantity,
        "unit": row.unit,
        "unit_price": float(row.unit_price) if row.unit_price is not None else None,
        "amount": float(row.amount),
        "currency": row.currency,
        "status": row.status.value if hasattr(row.status, "value") else row.status,
        "media_quote_id": str(row.media_quote_id) if row.media_quote_id else None,
        "media_quote": quote_payload(quote, channel_name),
        "media_quote_channel_name": channel_name,
        "linked_receipt_count": linked_count,
        "remaining_quantity": remaining,
        "receipt_complete": bool(
            total_quantity is not None and linked_count >= total_quantity
        ),
        "receipts": [
            {
                "receipt_id": str(receipt.id),
                "task_id": str(receipt.task_id),
                "published_url": receipt.published_url,
                "received_at": receipt.received_at,
            }
            for receipt in receipts
        ],
        "requested_by": str(row.requested_by) if row.requested_by else None,
        "requested_by_name": names.get(row.requested_by),
        "approved_by": str(row.approved_by) if row.approved_by else None,
        "approved_by_name": names.get(row.approved_by),
        "approved_at": row.approved_at,
        "note": row.note,
        "decision_note": row.decision_note,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def list_related(
    db: Session, project_id: uuid.UUID, rows: list[BudgetApproval]
) -> tuple[dict, dict, dict]:
    """一次把「报价 / 渠道名 / 已挂回执数」三张关联取齐。"""
    quote_ids = {row.media_quote_id for row in rows if row.media_quote_id}
    quotes: dict[uuid.UUID, MediaQuote] = {}
    channel_names: dict[uuid.UUID, str] = {}
    if quote_ids:
        quotes = {
            quote.id: quote
            for quote in db.scalars(
                select(MediaQuote).where(
                    MediaQuote.project_id == project_id,
                    MediaQuote.id.in_(quote_ids),
                )
            ).all()
        }
        channel_ids = {quote.channel_id for quote in quotes.values() if quote.channel_id}
        if channel_ids:
            channel_names = {
                channel_id: name
                for channel_id, name in db.execute(
                    select(Channel.id, Channel.name).where(
                        Channel.project_id == project_id,
                        Channel.id.in_(channel_ids),
                    )
                ).all()
            }
    budget_ids = [row.id for row in rows]
    counts: dict[uuid.UUID, int] = {}
    if budget_ids:
        counts = {
            budget_id: count
            for budget_id, count in db.execute(
                select(PublishReceipt.budget_approval_id, func.count())
                .where(
                    PublishReceipt.project_id == project_id,
                    PublishReceipt.budget_approval_id.in_(budget_ids),
                )
                .group_by(PublishReceipt.budget_approval_id)
            ).all()
        }
    return quotes, channel_names, counts


def load_detail(db: Session, project_id: uuid.UUID, row: BudgetApproval) -> dict:
    quote = None
    channel_name = None
    if row.media_quote_id is not None:
        quote = db.scalar(
            select(MediaQuote).where(
                MediaQuote.project_id == project_id,
                MediaQuote.id == row.media_quote_id,
            )
        )
        if quote is not None and quote.channel_id is not None:
            channel_name = db.scalar(
                select(Channel.name).where(
                    Channel.project_id == project_id,
                    Channel.id == quote.channel_id,
                )
            )
    receipts = db.scalars(
        select(PublishReceipt)
        .where(
            PublishReceipt.project_id == project_id,
            PublishReceipt.budget_approval_id == row.id,
        )
        .order_by(PublishReceipt.received_at.asc(), PublishReceipt.id.asc())
    ).all()
    return serialize(
        row,
        user_names(db, [row]),
        quote=quote,
        channel_name=channel_name,
        linked_count=len(receipts),
        receipts=list(receipts),
    )


def page_rows(
    db: Session, filters, *, page: int, page_size: int
) -> tuple[list[BudgetApproval], int]:
    total = (
        db.scalar(select(func.count()).select_from(BudgetApproval).where(*filters)) or 0
    )
    rows = db.scalars(
        select(BudgetApproval)
        .where(*filters)
        .order_by(BudgetApproval.created_at.desc(), BudgetApproval.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), int(total)


def list_payloads(db: Session, project_id: uuid.UUID, rows: list[BudgetApproval]) -> list[dict]:
    """列表页每条预算的展示快照：姓名与三张关联只各查一次。"""
    names = user_names(db, list(rows))
    quotes, channel_names, counts = list_related(db, project_id, list(rows))
    payloads = []
    for row in rows:
        quote = quotes.get(row.media_quote_id) if row.media_quote_id else None
        channel_name = (
            channel_names.get(quote.channel_id) if quote is not None and quote.channel_id else None
        )
        payloads.append(
            serialize(
                row,
                names,
                quote=quote,
                channel_name=channel_name,
                linked_count=counts.get(row.id, 0),
            )
        )
    return payloads
