"""页面审批记录的读取与查重，从 `api/page_approvals.py` 下沉。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.core.errors import ResourceMissingError
from app.models import Channel, PageApproval, User
from app.models.enums import CitationPageType, PageApprovalStatus, PagePermission
from app.services.page_approval_service import page_approval_can_publish


def approval_row(
    db: Session, project_id: uuid.UUID, approval_id: uuid.UUID, *, for_update: bool = False
) -> PageApproval:
    query = select(PageApproval).where(
        PageApproval.project_id == project_id,
        PageApproval.id == approval_id,
    )
    if for_update:
        query = query.with_for_update()
    approval = db.scalar(query)
    if approval is None:
        raise ResourceMissingError("页面审批记录不存在", code="page_approval_missing")
    return approval


def approval_payload(
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


def related_names(
    db: Session, approval: PageApproval
) -> tuple[str | None, str | None, str | None]:
    """详情页的三处关联：渠道名、申请人、复核人。"""
    channel = db.get(Channel, approval.channel_id)
    requester = db.get(User, approval.requested_by)
    reviewer = db.get(User, approval.reviewed_by) if approval.reviewed_by else None
    return (
        channel.name if channel else None,
        requester.display_name if requester else None,
        reviewer.display_name if reviewer else None,
    )


def existing_by_url_key(
    db: Session,
    project_id: uuid.UUID,
    channel_id: uuid.UUID,
    url_key_value: str,
) -> PageApproval | None:
    return db.scalar(
        select(PageApproval).where(
            PageApproval.project_id == project_id,
            PageApproval.channel_id == channel_id,
            PageApproval.url_key == url_key_value,
        )
    )


def page_approvals(
    db: Session,
    project_id: uuid.UUID,
    *,
    channel_id: uuid.UUID | None,
    page_type: CitationPageType | None,
    permission: PagePermission | None,
    status: PageApprovalStatus | None,
    q: str | None,
    page: int,
    page_size: int,
) -> tuple[int, list[tuple[PageApproval, str | None, str | None, str | None]]]:
    filters = [PageApproval.project_id == project_id]
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
    return int(total), [(row[0], row[1], row[2], row[3]) for row in rows]
