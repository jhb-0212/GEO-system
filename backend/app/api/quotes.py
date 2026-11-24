"""媒体报价：提交按 content.write，审批按 content.review。

状态只有 pending → approved / rejected / withdrawn；待审批可撤回，
已审批或已驳回后锁定，不重新打开。撤回保留报价记录并写审计，不做物理删除。
预算 = unit_price × quantity，审批时落 approved_by / approved_at。
"""

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_any_permission, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    Envelope,
    PagedEnvelope,
    QuoteCreated,
    QuoteData,
    ok,
    ok_page,
)
from app.core.errors import AppError, ConflictError
from app.db.session import get_db
from app.models import MediaQuote
from app.models.enums import QuoteStatus
from app.schemas import QuoteCreate, QuoteReview, QuoteUpdate
from app.services.audit import record_audit
from app.services.quote_listing import (
    ensure_channel_exists as _ensure_channel,
    load_quote_data as _load_quote_data,
    page_quotes as _page_quotes,
    plan_row as _ensure_plan,
    quote_creator_id as _quote_creator_id,
    quote_row as _get_quote,
)
from app.services.state_machine import ensure_quote_transition

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/media-quotes",
    tags=["媒体报价"],
    responses=COMMON_ERRORS,
)


@router.get("", response_model=PagedEnvelope[QuoteData])
def list_quotes(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    status: QuoteStatus | None = None,
    plan_id: uuid.UUID | None = None,
    channel_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    rows, total = _page_quotes(
        db,
        ctx.project.id,
        status=status,
        plan_id=plan_id,
        channel_id=channel_id,
        page=page,
        page_size=page_size,
    )
    return ok_page(
        rows,
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", status_code=201, response_model=Envelope[QuoteCreated])
def create_quote(
    payload: QuoteCreate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_plan(db, ctx.project.id, payload.plan_id)
    _ensure_channel(db, ctx.project.id, payload.channel_id)

    quote = MediaQuote(
        project_id=ctx.project.id,
        plan_id=payload.plan_id,
        channel_id=payload.channel_id,
        unit_price=payload.unit_price,
        quantity=payload.quantity,
        currency=payload.currency,
        status=QuoteStatus.PENDING,
        note=payload.note,
    )
    db.add(quote)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="quote.create",
        target_type="media_quote",
        target_id=quote.id,
        payload={
            "plan_id": str(quote.plan_id),
            "unit_price": str(quote.unit_price),
            "quantity": quote.quantity,
            "currency": quote.currency,
        },
    )
    db.commit()
    return ok({"id": str(quote.id), "status": quote.status.value})


@router.patch("/{quote_id}", response_model=Envelope[QuoteData])
def update_quote(
    quote_id: uuid.UUID,
    payload: QuoteUpdate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    quote = _get_quote(db, ctx.project.id, quote_id, for_update=True)
    if quote.status != QuoteStatus.PENDING:
        raise ConflictError("报价已结束审批，不能再修改", code="quote_status_conflict")

    changes = payload.model_dump(exclude_unset=True)
    for field in ("unit_price", "quantity", "currency"):
        if field in changes and changes[field] is None:
            raise AppError(f"{field} 不能为空", code="invalid_quote_update")
    if "channel_id" in changes:
        _ensure_channel(db, ctx.project.id, changes["channel_id"])

    audit_changes: dict[str, object] = {}
    for key, value in changes.items():
        setattr(quote, key, value)
        if isinstance(value, uuid.UUID):
            audit_changes[key] = str(value)
        else:
            audit_changes[key] = str(value) if key == "unit_price" else value
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="quote.update",
        target_type="media_quote",
        target_id=quote.id,
        payload={"changes": audit_changes},
    )
    db.commit()
    return ok(_load_quote_data(db, quote))


@router.post("/{quote_id}/withdraw", response_model=Envelope[QuoteData])
def withdraw_quote(
    quote_id: uuid.UUID,
    ctx: ProjectContext = Depends(
        require_any_permission("content.write", "content.review")
    ),
    db: Session = Depends(get_db),
) -> dict:
    """撤回待审批报价：保留原记录并写审计，不物理删除。

    撤回是提交人或审批人停止这笔报价流转的动作；已通过或已驳回后锁定，
    不能撤回，避免已进入预算口径的报价被事后改写。
    """
    quote = _get_quote(db, ctx.project.id, quote_id, for_update=True)
    if quote.status != QuoteStatus.PENDING:
        raise ConflictError(
            "只有待审批的报价可以撤回；已通过或已驳回的报价已锁定。",
            code="quote_status_conflict",
        )

    from_status = quote.status.value
    quote.status = ensure_quote_transition(quote.status, QuoteStatus.WITHDRAWN)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="quote.withdraw",
        target_type="media_quote",
        target_id=quote.id,
        payload={"from": from_status, "to": QuoteStatus.WITHDRAWN.value},
    )
    db.commit()
    return ok(_load_quote_data(db, quote))


@router.post("/{quote_id}/review", response_model=Envelope[QuoteData])
def review_quote(
    quote_id: uuid.UUID,
    payload: QuoteReview,
    ctx: ProjectContext = Depends(require_permission("content.review")),
    db: Session = Depends(get_db),
) -> dict:
    quote = _get_quote(db, ctx.project.id, quote_id, for_update=True)
    if quote.status != QuoteStatus.PENDING:
        raise ConflictError("报价已结束审批，不能重复审批", code="quote_status_conflict")
    # 职责分离：提交人不能审批自己提交的报价
    creator_id = _quote_creator_id(db, ctx.project.id, quote.id)
    if creator_id is not None and creator_id == ctx.user.id:
        raise AppError("不能审批自己提交的报价", code="review_self_not_allowed")

    if payload.decision.value == "approved":
        quote.status = ensure_quote_transition(quote.status, QuoteStatus.APPROVED)
        quote.approved_by = ctx.user.id
        quote.approved_at = datetime.now(timezone.utc)
    else:
        quote.status = ensure_quote_transition(quote.status, QuoteStatus.REJECTED)
    if payload.note is not None:
        quote.note = payload.note

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="quote.review",
        target_type="media_quote",
        target_id=quote.id,
        payload={"decision": quote.status.value, "note": payload.note},
    )
    db.commit()
    return ok(_load_quote_data(db, quote))
