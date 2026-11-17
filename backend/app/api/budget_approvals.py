"""预算审批：四类费用统一申请、审批与留痕。

能力门禁：
- 查看 `budget.read`
- 提交 `budget.write`
- 通过/驳回 `budget.approve`
"""

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    BudgetApprovalData,
    Envelope,
    PagedEnvelope,
    ok,
    ok_page,
)
from app.core.errors import AppError
from app.db.session import get_db
from app.models import BudgetApproval, User
from app.models.enums import BudgetApprovalStatus, BudgetCategory, ReviewDecision
from app.schemas import BudgetApprovalCreate, BudgetApprovalReview
from app.services.audit import record_audit
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


def _serialize(row: BudgetApproval, names: dict | None = None) -> dict:
    names = names or {}
    return {
        "id": str(row.id),
        "category": row.category.value if hasattr(row.category, "value") else row.category,
        "title": row.title,
        "quantity": float(row.quantity) if row.quantity is not None else None,
        "unit": row.unit,
        "unit_price": float(row.unit_price) if row.unit_price is not None else None,
        "amount": float(row.amount),
        "currency": row.currency,
        "status": row.status.value if hasattr(row.status, "value") else row.status,
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
        .order_by(BudgetApproval.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    names = _user_names(db, rows)
    return ok_page(
        [_serialize(row, names) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", status_code=201, response_model=Envelope[BudgetApprovalData])
def create_budget_approval(
    payload: BudgetApprovalCreate,
    ctx: ProjectContext = Depends(require_permission("budget.write")),
    db: Session = Depends(get_db),
) -> dict:
    row = BudgetApproval(
        project_id=ctx.project.id,
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
        },
    )
    db.commit()
    db.refresh(row)
    return ok(_serialize(row, _user_names(db, [row])))


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
    return ok(_serialize(row, _user_names(db, [row])))
