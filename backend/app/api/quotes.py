"""媒体报价：提交按 content.write，审批按 content.review。

状态只有 pending → approved / rejected / withdrawn；待审批可撤回，
已审批或已驳回后锁定，不重新打开。撤回保留报价记录并写审计，不做物理删除。
预算 = unit_price × quantity，审批时落 approved_by / approved_at。
"""

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
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
from app.core.errors import AppError, ConflictError, ResourceMissingError
from app.db.session import get_db
from app.models import AuditLog, Channel, ContentPlan, MediaQuote, User
from app.models.enums import QuoteStatus
from app.schemas import QuoteCreate, QuoteReview, QuoteUpdate
from app.services.audit import record_audit

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/media-quotes",
    tags=["媒体报价"],
    responses=COMMON_ERRORS,
)


def _get_quote(db: Session, project_id: uuid.UUID, quote_id: uuid.UUID, *, for_update: bool = False) -> MediaQuote:
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


def _ensure_plan(db: Session, project_id: uuid.UUID, plan_id: uuid.UUID) -> ContentPlan:
    plan = db.scalar(
        select(ContentPlan).where(
            ContentPlan.project_id == project_id,
            ContentPlan.id == plan_id,
        )
    )
    if plan is None:
        raise ResourceMissingError("运营计划不存在", code="plan_missing")
    return plan


def _ensure_channel(db: Session, project_id: uuid.UUID, channel_id: uuid.UUID | None) -> None:
    if channel_id is None:
        return
    if db.scalar(select(Channel.id).where(Channel.project_id == project_id, Channel.id == channel_id)) is None:
        raise ResourceMissingError("渠道不存在", code="channel_missing")


def _quote_data(
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


def _load_quote_data(db: Session, quote: MediaQuote) -> dict:
    plan_title = db.scalar(select(ContentPlan.title).where(ContentPlan.id == quote.plan_id))
    channel_name = None
    if quote.channel_id is not None:
        channel_name = db.scalar(select(Channel.name).where(Channel.id == quote.channel_id))
    approved_by_name = None
    if quote.approved_by is not None:
        approved_by_name = db.scalar(select(User.display_name).where(User.id == quote.approved_by))
    return _quote_data(
        quote,
        plan_title=plan_title,
        channel_name=channel_name,
        approved_by_name=approved_by_name,
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
    filters = [MediaQuote.project_id == ctx.project.id]
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
    return ok_page(
        [
            _quote_data(
                quote,
                plan_title=plan_title,
                channel_name=channel_name,
                approved_by_name=approved_by_name,
            )
            for quote, plan_title, channel_name, approved_by_name in rows
        ],
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


def _quote_creator_id(db: Session, project_id: uuid.UUID, quote_id: uuid.UUID) -> uuid.UUID | None:
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
    quote.status = QuoteStatus.WITHDRAWN
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
        quote.status = QuoteStatus.APPROVED
        quote.approved_by = ctx.user.id
        quote.approved_at = datetime.now(timezone.utc)
    else:
        quote.status = QuoteStatus.REJECTED
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
