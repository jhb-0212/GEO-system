"""媒体报价的读取、关联校验与分页，从 `api/quotes.py` 下沉。

约定：这里只做「取数 + 组装」，状态迁移与权限仍在 api / `state_machine`。
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ResourceMissingError
from app.models import AuditLog, Channel, ContentPlan, MediaQuote, User
from app.models.enums import QuoteStatus


def quote_row(
    db: Session,
    project_id: uuid.UUID,
    quote_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> MediaQuote:
    query = select(MediaQuote).where(
        MediaQuote.project_id == project_id,
        MediaQuote.id == quote_id,
    )
    if for_update:
        query = query.with_for_update()
    quote = db.scalar(query)
    if quote is None:
        raise ResourceMissingError("报价不存在", code="quote_missing")
    return quote


def plan_row(db: Session, project_id: uuid.UUID, plan_id: uuid.UUID) -> ContentPlan:
    plan = db.scalar(
        select(ContentPlan).where(
            ContentPlan.project_id == project_id,
            ContentPlan.id == plan_id,
        )
    )
    if plan is None:
        raise ResourceMissingError("运营计划不存在", code="plan_missing")
    return plan


def ensure_channel_exists(
    db: Session, project_id: uuid.UUID, channel_id: uuid.UUID | None
) -> None:
    """报价上的渠道可空；给了就必须属于本项目。"""
    if channel_id is None:
        return
    if (
        db.scalar(
            select(Channel.id).where(
                Channel.project_id == project_id,
                Channel.id == channel_id,
            )
        )
        is None
    ):
        raise ResourceMissingError("渠道不存在", code="channel_missing")


def quote_payload(
    quote: MediaQuote,
    *,
    plan_title: str | None,
    channel_name: str | None,
    approved_by_name: str | None,
) -> dict:
    budget = quote.unit_price * quote.quantity
    return {
        "id": str(quote.id),
        "plan_id": str(quote.plan_id),
        "plan_title": plan_title,
        "channel_id": str(quote.channel_id) if quote.channel_id else None,
        "channel_name": channel_name,
        "unit_price": float(quote.unit_price),
        "quantity": quote.quantity,
        "currency": quote.currency,
        "budget": float(budget),
        "status": quote.status.value,
        "approved_by": str(quote.approved_by) if quote.approved_by else None,
        "approved_by_name": approved_by_name,
        "approved_at": quote.approved_at,
        "note": quote.note,
        "created_at": quote.created_at,
        "updated_at": quote.updated_at,
    }


def load_quote_data(db: Session, quote: MediaQuote) -> dict:
    """单条报价的详情：三处关联各取一次。"""
    plan_title = db.scalar(select(ContentPlan.title).where(ContentPlan.id == quote.plan_id))
    channel_name = None
    if quote.channel_id is not None:
        channel_name = db.scalar(select(Channel.name).where(Channel.id == quote.channel_id))
    approved_by_name = None
    if quote.approved_by is not None:
        approved_by_name = db.scalar(
            select(User.display_name).where(User.id == quote.approved_by)
        )
    return quote_payload(
        quote,
        plan_title=plan_title,
        channel_name=channel_name,
        approved_by_name=approved_by_name,
    )


def page_quotes(
    db: Session,
    project_id: uuid.UUID,
    *,
    status: QuoteStatus | None,
    plan_id: uuid.UUID | None,
    channel_id: uuid.UUID | None,
    page: int,
    page_size: int,
) -> tuple[list[dict], int]:
    """列表页：一条联表取齐计划标题 / 渠道名 / 审批人，计数一次。"""
    filters = [MediaQuote.project_id == project_id]
    if status is not None:
        filters.append(MediaQuote.status == status)
    if plan_id is not None:
        filters.append(MediaQuote.plan_id == plan_id)
    if channel_id is not None:
        filters.append(MediaQuote.channel_id == channel_id)

    total = db.scalar(select(func.count()).select_from(MediaQuote).where(*filters)) or 0
    rows = db.execute(
        select(MediaQuote, ContentPlan.title, Channel.name, User.display_name)
        .join(ContentPlan, ContentPlan.id == MediaQuote.plan_id)
        .outerjoin(Channel, Channel.id == MediaQuote.channel_id)
        .outerjoin(User, User.id == MediaQuote.approved_by)
        .where(*filters)
        .order_by(MediaQuote.created_at.desc(), MediaQuote.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return (
        [
            quote_payload(
                quote,
                plan_title=plan_title,
                channel_name=channel_name,
                approved_by_name=approved_by_name,
            )
            for quote, plan_title, channel_name, approved_by_name in rows
        ],
        total,
    )


def quote_creator_id(
    db: Session, project_id: uuid.UUID, quote_id: uuid.UUID
) -> uuid.UUID | None:
    """报价的提交人取自 quote.create 审计留痕（表上不重复存 created_by）。"""
    return db.scalar(
        select(AuditLog.actor_id)
        .where(
            AuditLog.project_id == project_id,
            AuditLog.action == "quote.create",
            AuditLog.target_id == quote_id,
        )
        .order_by(AuditLog.created_at.asc())
        .limit(1)
    )
