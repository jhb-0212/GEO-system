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
from app.services.state_machine import ensure_budget_approval_transition
from app.core.errors import AppError
from app.db.session import get_db
from app.models import (
    BudgetApproval,
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
from app.services.budget_listing import (
    list_payloads as _list_payloads,
    load_detail as _load_detail,
    page_rows as _page_rows,
)
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
    rows, total = _page_rows(db, filters, page=page, page_size=page_size)
    return ok_page(
        _list_payloads(db, ctx.project.id, rows),
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

    row.status = ensure_budget_approval_transition(
        row.status,
        BudgetApprovalStatus.APPROVED
        if payload.decision == ReviewDecision.APPROVED
        else BudgetApprovalStatus.REJECTED,
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
