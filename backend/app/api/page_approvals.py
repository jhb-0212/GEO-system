"""页面级发布审批：逐页登记、审批、驳回、撤销；审批与渠道准入正交。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    Envelope,
    PageApprovalData,
    PagedEnvelope,
    ok,
    ok_page,
)
from app.core.errors import BusinessValidationError, ConflictError, ReviewStateError
from app.db.session import get_db
from app.models import Channel, PageApproval, User
from app.models.enums import (
    CitationPageType,
    PageApprovalStatus,
    PagePermission,
    ReviewDecision,
)
from app.schemas import PageApprovalCreate, PageApprovalReview, PageApprovalRevoke
from app.services.audit import record_audit
from app.services.channel_access import ensure_channel_approved
from app.services.citation_attribution import canonical_url, url_key
from app.services.page_approval_service import (
    PAGE_APPROVAL_REQUIRED_PAGE_TYPES,
    page_approval_can_publish,
    page_type_for_url,
)
from app.services.project_scope import require_scoped_row

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/page-approvals",
    tags=["页面审批"],
    responses=COMMON_ERRORS,
)


def _get_approval(
    db: Session,
    project_id: uuid.UUID,
    approval_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> PageApproval:
    query = select(PageApproval).where(
        PageApproval.project_id == project_id,
        PageApproval.id == approval_id,
    )
    if for_update:
        query = query.with_for_update()
    approval = db.scalar(query)
    if approval is None:
        from app.core.errors import ResourceMissingError

        raise ResourceMissingError("页面审批记录不存在", code="page_approval_missing")
    return approval


def _approval_data(
    approval: PageApproval,
    *,
    channel_name: str | None,
    requested_by_name: str | None,
    reviewed_by_name: str | None,
) -> dict:
    return {
        "id": str(approval.id),
        "channel_id": str(approval.channel_id),
        "channel_name": channel_name,
        "page_url": approval.page_url,
        "normalized_url": approval.normalized_url,
        "url_key": approval.url_key,
        "title": approval.title,
        "page_type": approval.page_type.value,
        "permission": approval.permission.value,
        "status": approval.status.value,
        "can_publish": page_approval_can_publish(approval),
        "requested_by": str(approval.requested_by),
        "requested_by_name": requested_by_name,
        "reviewed_by": str(approval.reviewed_by) if approval.reviewed_by else None,
        "reviewed_by_name": reviewed_by_name,
        "reviewed_at": approval.reviewed_at,
        "review_note": approval.review_note,
        "created_at": approval.created_at,
        "updated_at": approval.updated_at,
    }


@router.get("", response_model=PagedEnvelope[PageApprovalData])
def list_page_approvals(
    ctx: ProjectContext = Depends(require_permission("publish.read")),
    db: Session = Depends(get_db),
    channel_id: uuid.UUID | None = None,
    page_type: CitationPageType | None = None,
    permission: PagePermission | None = None,
    status: PageApprovalStatus | None = None,
    q: str | None = Query(default=None, max_length=255),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    filters = [PageApproval.project_id == ctx.project.id]
    if channel_id is not None:
        filters.append(PageApproval.channel_id == channel_id)
    if page_type is not None:
        filters.append(PageApproval.page_type == page_type)
    if permission is not None:
        filters.append(PageApproval.permission == permission)
    if status is not None:
        filters.append(PageApproval.status == status)
    if q and q.strip():
        like = f"%{q.strip()}%"
        filters.append(
            or_(
                PageApproval.page_url.ilike(like),
                PageApproval.normalized_url.ilike(like),
                PageApproval.title.ilike(like),
                PageApproval.review_note.ilike(like),
            )
        )

    total = db.scalar(select(func.count()).select_from(PageApproval).where(*filters)) or 0
    requested_user = aliased(User)
    reviewed_user = aliased(User)
    rows = db.execute(
        select(
            PageApproval,
            Channel.name,
            requested_user.display_name,
            reviewed_user.display_name,
        )
        .join(Channel, Channel.id == PageApproval.channel_id)
        .join(requested_user, requested_user.id == PageApproval.requested_by)
        .outerjoin(reviewed_user, reviewed_user.id == PageApproval.reviewed_by)
        .where(*filters)
        .order_by(PageApproval.created_at.desc(), PageApproval.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page(
        [
            _approval_data(
                approval,
                channel_name=channel_name,
                requested_by_name=requested_name,
                reviewed_by_name=reviewed_name,
            )
            for approval, channel_name, requested_name, reviewed_name in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/{approval_id}", response_model=Envelope[PageApprovalData])
def get_page_approval(
    approval_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("publish.read")),
    db: Session = Depends(get_db),
) -> dict:
    approval = _get_approval(db, ctx.project.id, approval_id)
    channel = db.get(Channel, approval.channel_id)
    requester = db.get(User, approval.requested_by)
    reviewer = db.get(User, approval.reviewed_by) if approval.reviewed_by else None
    return ok(
        _approval_data(
            approval,
            channel_name=channel.name if channel else None,
            requested_by_name=requester.display_name if requester else None,
            reviewed_by_name=reviewer.display_name if reviewer else None,
        )
    )


@router.post("", status_code=201, response_model=Envelope[PageApprovalData])
def create_page_approval(
    payload: PageApprovalCreate,
    ctx: ProjectContext = Depends(require_permission("publish.execute")),
    db: Session = Depends(get_db),
) -> dict:
    channel = require_scoped_row(
        db, Channel, ctx.project.id, resource="channel", id=payload.channel_id
    )
    if not channel.is_active:
        raise ReviewStateError("渠道已停用，不能登记页面审批")
    ensure_channel_approved(channel)
    detected_type = page_type_for_url(payload.page_url, payload.title)
    if (
        payload.page_type in PAGE_APPROVAL_REQUIRED_PAGE_TYPES
        or detected_type in PAGE_APPROVAL_REQUIRED_PAGE_TYPES
    ) and payload.page_type != detected_type:
        raise BusinessValidationError(
            "页面审批登记的页型与 URL/标题分类不一致，请按实际页面选择",
            code="page_approval_type_mismatch",
        )

    key = url_key(payload.page_url)
    existing = db.scalar(
        select(PageApproval).where(
            PageApproval.project_id == ctx.project.id,
            PageApproval.channel_id == channel.id,
            PageApproval.url_key == key,
        )
    )
    if existing is not None:
        raise ConflictError(
            "同一渠道下该页面已登记过页面审批",
            code="page_approval_exists",
        )

    approval = PageApproval(
        project_id=ctx.project.id,
        channel_id=channel.id,
        page_url=payload.page_url.strip(),
        normalized_url=canonical_url(payload.page_url),
        url_key=key,
        title=payload.title,
        page_type=payload.page_type,
        permission=payload.permission,
        status=PageApprovalStatus.PENDING,
        requested_by=ctx.user.id,
    )
    db.add(approval)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            "同一渠道下该页面已登记过页面审批",
            code="page_approval_exists",
        ) from exc

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="page_approval.create",
        target_type="page_approval",
        target_id=approval.id,
        payload={
            "channel_id": str(channel.id),
            "page_url": approval.page_url,
            "page_type": approval.page_type.value,
            "permission": approval.permission.value,
        },
    )
    db.commit()
    return ok(
        _approval_data(
            approval,
            channel_name=channel.name,
            requested_by_name=ctx.user.display_name,
            reviewed_by_name=None,
        )
    )


@router.post("/{approval_id}/review", response_model=Envelope[PageApprovalData])
def review_page_approval(
    approval_id: uuid.UUID,
    payload: PageApprovalReview,
    ctx: ProjectContext = Depends(require_permission("channel.approve")),
    db: Session = Depends(get_db),
) -> dict:
    approval = _get_approval(db, ctx.project.id, approval_id, for_update=True)
    if approval.status != PageApprovalStatus.PENDING:
        raise ReviewStateError("只有待审批的页面可以审批", code="page_approval_state_conflict")

    approval.status = (
        PageApprovalStatus.APPROVED
        if payload.decision == ReviewDecision.APPROVED
        else PageApprovalStatus.REJECTED
    )
    approval.reviewed_by = ctx.user.id
    approval.reviewed_at = datetime.now(timezone.utc)
    approval.review_note = (payload.note or "").strip() or None

    channel = db.get(Channel, approval.channel_id)
    requester = db.get(User, approval.requested_by)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="page_approval.review",
        target_type="page_approval",
        target_id=approval.id,
        payload={
            "decision": approval.status.value,
            "page_url": approval.page_url,
            "page_type": approval.page_type.value,
            "permission": approval.permission.value,
            "note": approval.review_note,
        },
    )
    db.commit()
    return ok(
        _approval_data(
            approval,
            channel_name=channel.name if channel else None,
            requested_by_name=requester.display_name if requester else None,
            reviewed_by_name=ctx.user.display_name,
        )
    )


@router.post("/{approval_id}/revoke", response_model=Envelope[PageApprovalData])
def revoke_page_approval(
    approval_id: uuid.UUID,
    payload: PageApprovalRevoke,
    ctx: ProjectContext = Depends(require_permission("channel.approve")),
    db: Session = Depends(get_db),
) -> dict:
    approval = _get_approval(db, ctx.project.id, approval_id, for_update=True)
    if approval.status != PageApprovalStatus.APPROVED:
        raise ReviewStateError("只有已批准的页面可以撤销", code="page_approval_state_conflict")

    approval.status = PageApprovalStatus.REVOKED
    approval.reviewed_by = ctx.user.id
    approval.reviewed_at = datetime.now(timezone.utc)
    approval.review_note = payload.note
    channel = db.get(Channel, approval.channel_id)
    requester = db.get(User, approval.requested_by)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="page_approval.revoke",
        target_type="page_approval",
        target_id=approval.id,
        payload={
            "page_url": approval.page_url,
            "note": payload.note,
        },
    )
    db.commit()
    return ok(
        _approval_data(
            approval,
            channel_name=channel.name if channel else None,
            requested_by_name=requester.display_name if requester else None,
            reviewed_by_name=ctx.user.display_name,
        )
    )
