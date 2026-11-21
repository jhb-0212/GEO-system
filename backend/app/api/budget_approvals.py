"""预算审批：四类费用统一申请、审批与留痕。

P76 起，媒体投放预算必须绑定已批准的媒体报价；回执可逐条挂到预算。
能力门禁：
- 查看 `budget.read`
- 提交 `budget.write`
- 通过/驳回 `budget.approve`
- 挂/解绑回执 `budget.write` 或 `budget.approve`
"""

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_any_permission, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    BudgetApprovalData,
    BudgetReceiptLinkResult,
    Envelope,
    PagedEnvelope,
    ok,
    ok_page,
)
from app.core.errors import AppError
from app.db.session import get_db
from app.models import (
    BudgetApproval,
    Channel,
    MediaQuote,
    PublishReceipt,
    User,
)
from app.models.enums import BudgetApprovalStatus, BudgetCategory, ReviewDecision
from app.schemas import (
    BudgetApprovalCreate,
    BudgetApprovalReview,
    BudgetReceiptLinkCreate,
)
from app.services.access import project_has_capability_holder
from app.services.audit import record_audit
from app.services.budget_receipts import (
    link_receipt_to_budget,
    receipt_link_summary,
    unlink_receipt_from_budget,
    validate_media_budget_quote,
)
from app.services.project_scope import require_scoped_row

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/budget-approvals",
    tags=["预算审批"],
    responses=COMMON_ERRORS,
)


def _user_names(db: Session, rows: list[BudgetApproval]) -> dict:
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


def _quote_data(quote: MediaQuote | None, channel_name: str | None) -> dict | None:
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


def _serialize(
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
        "media_quote": _quote_data(quote, channel_name),
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


def _list_related(db: Session, project_id: uuid.UUID, rows: list[BudgetApproval]) -> tuple:
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


def _load_detail(db: Session, project_id: uuid.UUID, row: BudgetApproval) -> dict:
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
    return _serialize(
        row,
        _user_names(db, [row]),
        quote=quote,
        channel_name=channel_name,
        linked_count=len(receipts),
        receipts=list(receipts),
    )


@router.get("", response_model=PagedEnvelope[BudgetApprovalData])
def list_budget_approvals(
    ctx: ProjectContext = Depends(require_permission("budget.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: BudgetApprovalStatus | None = Query(default=None),
    category: BudgetCategory | None = Query(default=None),
) -> dict:
    filters = [BudgetApproval.project_id == ctx.project.id]
    if status is not None:
        filters.append(BudgetApproval.status == status)
    if category is not None:
        filters.append(BudgetApproval.category == category)
    total = db.scalar(select(func.count()).select_from(BudgetApproval).where(*filters)) or 0
    rows = db.scalars(
        select(BudgetApproval)
        .where(*filters)
        .order_by(BudgetApproval.created_at.desc(), BudgetApproval.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    names = _user_names(db, list(rows))
    quotes, channel_names, counts = _list_related(db, ctx.project.id, list(rows))
    return ok_page(
        [
            _serialize(
                row,
                names,
                quote=quotes.get(row.media_quote_id) if row.media_quote_id else None,
                channel_name=(
                    channel_names.get(quotes[row.media_quote_id].channel_id)
                    if row.media_quote_id in quotes
                    and quotes[row.media_quote_id].channel_id
                    else None
                ),
                linked_count=counts.get(row.id, 0),
            )
            for row in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/{budget_id}", response_model=Envelope[BudgetApprovalData])
def get_budget_approval(
    budget_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("budget.read")),
    db: Session = Depends(get_db),
) -> dict:
    row = require_scoped_row(
        db,
        BudgetApproval,
        ctx.project.id,
        resource="预算申请",
        id=budget_id,
    )
    return ok(_load_detail(db, ctx.project.id, row))


@router.post("", status_code=201, response_model=Envelope[BudgetApprovalData])
def create_budget_approval(
    payload: BudgetApprovalCreate,
    ctx: ProjectContext = Depends(require_permission("budget.write")),
    db: Session = Depends(get_db),
) -> dict:
    if not project_has_capability_holder(
        db,
        project_id=ctx.project.id,
        permission="budget.approve",
        exclude_user_id=ctx.user.id,
    ):
        raise AppError(
            "当前项目没有其他预算审批人，提交后将无人可批；请先添加审核账号",
            code="budget_approver_required",
        )
    quote = validate_media_budget_quote(
        db,
        project_id=ctx.project.id,
        category=payload.category,
        media_quote_id=payload.media_quote_id,
        quantity=payload.quantity,
        unit_price=payload.unit_price,
        amount=payload.amount,
        currency=payload.currency,
    )
    row = BudgetApproval(
        project_id=ctx.project.id,
        media_quote_id=payload.media_quote_id,
        category=payload.category,
        title=payload.title.strip(),
        quantity=payload.quantity,
        unit=payload.unit,
        unit_price=payload.unit_price,
        amount=payload.amount,
        currency=payload.currency.upper(),
        status=BudgetApprovalStatus.PENDING,
        requested_by=ctx.user.id,
        note=payload.note,
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="budget.create",
        target_type="budget_approval",
        target_id=row.id,
        payload={
            "category": payload.category.value,
            "amount": str(payload.amount),
            "currency": row.currency,
            "media_quote_id": str(payload.media_quote_id)
            if payload.media_quote_id
            else None,
        },
    )
    db.commit()
    db.refresh(row)
    return ok(_load_detail(db, ctx.project.id, row))


@router.post(
    "/{budget_id}/review",
    response_model=Envelope[BudgetApprovalData],
)
def review_budget_approval(
    payload: BudgetApprovalReview,
    budget_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("budget.approve")),
    db: Session = Depends(get_db),
) -> dict:
    row = require_scoped_row(
        db,
        BudgetApproval,
        ctx.project.id,
        resource="预算申请",
        for_update=True,
        id=budget_id,
    )
    if row.status != BudgetApprovalStatus.PENDING:
        raise AppError("该预算申请已处理，不能重复审批", code="budget_already_reviewed")
    # 职责分离：提交人不能审批自己提交的预算，与内容版本 / 媒体报价保持同一口径。
    if row.requested_by == ctx.user.id:
        raise AppError("不能审批自己提交的预算申请", code="review_self_not_allowed")
    if payload.decision == ReviewDecision.REJECTED and not (payload.note or "").strip():
        raise AppError("驳回预算必须填写原因", code="budget_reject_note_required")

    # 审批通过时再锁一次报价，避免两个预算同时抢同一报价的剩余篇数。
    if payload.decision == ReviewDecision.APPROVED:
        validate_media_budget_quote(
            db,
            project_id=ctx.project.id,
            category=row.category,
            media_quote_id=row.media_quote_id,
            quantity=row.quantity,
            unit_price=row.unit_price,
            amount=row.amount,
            currency=row.currency,
            exclude_budget_id=row.id,
        )

    row.status = (
        BudgetApprovalStatus.APPROVED
        if payload.decision == ReviewDecision.APPROVED
        else BudgetApprovalStatus.REJECTED
    )
    row.decision_note = (payload.note or "").strip() or None
    row.approved_by = ctx.user.id
    row.approved_at = datetime.now(timezone.utc)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="budget.approve" if row.status == BudgetApprovalStatus.APPROVED else "budget.reject",
        target_type="budget_approval",
        target_id=row.id,
        payload={"decision": row.status.value, "amount": str(row.amount)},
    )
    db.commit()
    db.refresh(row)
    return ok(_load_detail(db, ctx.project.id, row))


@router.post(
    "/{budget_id}/receipt-links",
    response_model=Envelope[BudgetReceiptLinkResult],
)
def link_receipt(
    budget_id: uuid.UUID,
    payload: BudgetReceiptLinkCreate,
    ctx: ProjectContext = Depends(
        require_any_permission("budget.write", "budget.approve")
    ),
    db: Session = Depends(get_db),
) -> dict:
    budget = require_scoped_row(
        db,
        BudgetApproval,
        ctx.project.id,
        resource="预算申请",
        for_update=True,
        id=budget_id,
    )
    receipt = require_scoped_row(
        db,
        PublishReceipt,
        ctx.project.id,
        resource="发布回执",
        for_update=True,
        id=payload.receipt_id,
    )
    linked, remaining = link_receipt_to_budget(
        db,
        project_id=ctx.project.id,
        budget=budget,
        receipt=receipt,
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="budget.receipt_link",
        target_type="budget_approval",
        target_id=budget.id,
        payload={
            "receipt_id": str(receipt.id),
            "published_url": receipt.published_url,
            "linked_receipt_count": linked,
        },
    )
    db.commit()
    return ok(
        {
            "budget_approval_id": str(budget.id),
            "receipt_id": str(receipt.id),
            "linked_receipt_count": linked,
            "remaining_quantity": remaining,
        }
    )


@router.delete(
    "/{budget_id}/receipt-links/{receipt_id}",
    response_model=Envelope[BudgetReceiptLinkResult],
)
def unlink_receipt(
    budget_id: uuid.UUID,
    receipt_id: uuid.UUID,
    ctx: ProjectContext = Depends(
        require_any_permission("budget.write", "budget.approve")
    ),
    db: Session = Depends(get_db),
) -> dict:
    budget = require_scoped_row(
        db,
        BudgetApproval,
        ctx.project.id,
        resource="预算申请",
        for_update=True,
        id=budget_id,
    )
    receipt = require_scoped_row(
        db,
        PublishReceipt,
        ctx.project.id,
        resource="发布回执",
        for_update=True,
        id=receipt_id,
    )
    linked, remaining = unlink_receipt_from_budget(
        db,
        project_id=ctx.project.id,
        budget=budget,
        receipt=receipt,
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="budget.receipt_unlink",
        target_type="budget_approval",
        target_id=budget.id,
        payload={
            "receipt_id": str(receipt.id),
            "published_url": receipt.published_url,
            "linked_receipt_count": linked,
        },
    )
    db.commit()
    return ok(
        {
            "budget_approval_id": str(budget.id),
            "receipt_id": str(receipt.id),
            "linked_receipt_count": linked,
            "remaining_quantity": remaining,
        }
    )
