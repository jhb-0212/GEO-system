"""内容接口：写正文要 content.write，审批要 content.review。

审核人员没有 content.write，改正文一律 403；审批必须写 content_hash_snapshot 留痕。
"""

import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    ContentBodyUpdated,
    ContentItemCreated,
    ContentReviewData,
    ContentReviewQueueItem,
    ContentReviewCreated,
    ContentVersionCreated,
    ContentVersionDetail,
    ContentVersionSubmitted,
    Envelope,
    PagedEnvelope,
    ok,
    ok_page,
)
from app.core.errors import ResourceMissingError, ReviewStateError
from app.db.session import get_db
from app.models import Channel, ContentItem, ContentReview, ContentVersion, User
from app.models.enums import ContentStatus, ReviewDecision
from app.schemas import (
    ContentBodyUpdate,
    ContentItemCreate,
    ContentReviewRequest,
    ContentVersionCreate,
)
from app.services.audit import record_audit
from app.services.project_scope import require_scoped_row
from app.services.state_machine import ensure_content_transition

router = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["内容与审核"],
    responses=COMMON_ERRORS,
)


def _content_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@router.get("/content-versions", response_model=PagedEnvelope[ContentReviewQueueItem])
def list_content_versions(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    status: ContentStatus = ContentStatus.PENDING_REVIEW,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    filters = [ContentVersion.project_id == ctx.project.id, ContentVersion.status == status]
    total = db.scalar(select(func.count()).select_from(ContentVersion).where(*filters)) or 0
    rows = db.execute(
        select(ContentVersion, ContentItem, User.display_name)
        .join(ContentItem, ContentItem.id == ContentVersion.item_id)
        .outerjoin(User, User.id == func.coalesce(ContentVersion.submitted_by, ContentVersion.created_by))
        .where(*filters, ContentItem.project_id == ctx.project.id)
        .order_by(ContentVersion.submitted_at.desc().nullslast(), ContentVersion.created_at.desc(), ContentVersion.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page(
        [
            {
                "version_id": str(version.id),
                "item_id": str(item.id),
                "title": item.title,
                "version_no": version.version_no,
                "status": version.status.value,
                "kind": item.kind.value,
                "channel_id": str(item.channel_id) if item.channel_id else None,
                "author_id": str(version.submitted_by or version.created_by) if version.submitted_by or version.created_by else None,
                "author_name": author_name,
                "submitted_at": version.submitted_at,
            }
            for version, item, author_name in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/content-versions/{version_id}", response_model=Envelope[ContentVersionDetail])
def get_content_version(
    version_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
) -> dict:
    version = require_scoped_row(db, ContentVersion, ctx.project.id, resource="content_version", id=version_id)
    item = require_scoped_row(db, ContentItem, ctx.project.id, resource="content_item", id=version.item_id)
    return ok({
        "version_id": str(version.id), "item_id": str(item.id), "title": item.title,
        "kind": item.kind.value, "channel_id": str(item.channel_id) if item.channel_id else None,
        "version_no": version.version_no, "status": version.status.value,
        "body": version.body, "content_hash": version.content_hash, "change_note": version.change_note,
    })


@router.post("/contents", status_code=201, response_model=Envelope[ContentItemCreated])
def create_content_item(
    payload: ContentItemCreate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    if payload.channel_id is not None:
        require_scoped_row(db, Channel, ctx.project.id, resource="channel", id=payload.channel_id)
    if payload.parent_id is not None:
        require_scoped_row(db, ContentItem, ctx.project.id, resource="parent_content", id=payload.parent_id)
    item = ContentItem(
        project_id=ctx.project.id,
        kind=payload.kind,
        title=payload.title,
        channel_id=payload.channel_id,
        parent_id=payload.parent_id,
        status=ContentStatus.DRAFT,
        created_by=ctx.user.id,
    )
    db.add(item)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="content.item_create",
        target_type="content_item",
        target_id=item.id,
        payload={"kind": payload.kind.value, "title": payload.title},
    )
    db.commit()
    return ok({"item_id": str(item.id)})


@router.post(
    "/contents/{item_id}/versions",
    status_code=201,
    response_model=Envelope[ContentVersionCreated],
)
def create_content_version(
    item_id: uuid.UUID,
    payload: ContentVersionCreate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    item = require_scoped_row(
        db, ContentItem, ctx.project.id, resource="content_item", for_update=True, id=item_id
    )
    current_max = db.scalar(
        select(func.max(ContentVersion.version_no)).where(ContentVersion.item_id == item.id)
    )
    next_no = (current_max or 0) + 1

    version = ContentVersion(
        project_id=ctx.project.id,
        item_id=item.id,
        version_no=next_no,
        body=payload.body,
        content_hash=_content_hash(payload.body),
        change_note=payload.change_note,
        status=ContentStatus.DRAFT,
        created_by=ctx.user.id,
    )
    db.add(version)
    db.flush()
    item.current_version_id = version.id
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="content.version_create",
        target_type="content_version",
        target_id=version.id,
        payload={"version_no": next_no, "content_hash": version.content_hash},
    )
    db.commit()
    return ok({"version_id": str(version.id), "version_no": next_no})


@router.patch("/content-versions/{version_id}/body", response_model=Envelope[ContentBodyUpdated])
def update_content_body(
    version_id: uuid.UUID,
    payload: ContentBodyUpdate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    """只有 content.write 能改正文；审核人员调用在这里被 403 挡下。"""
    version = require_scoped_row(
        db, ContentVersion, ctx.project.id, resource="content_version", for_update=True, id=version_id
    )
    if version.status != ContentStatus.DRAFT:
        raise ReviewStateError("只有草稿版本能修改正文，请创建新版本")
    item = require_scoped_row(db, ContentItem, ctx.project.id, resource="content_item", id=version.item_id)
    if item.current_version_id != version.id:
        raise ReviewStateError("只能修改当前内容版本")
    previous_hash = version.content_hash
    version.body = payload.body
    version.content_hash = _content_hash(payload.body)
    if payload.change_note:
        version.change_note = payload.change_note
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="content.body_update",
        target_type="content_version",
        target_id=version.id,
        payload={"before_hash": previous_hash, "after_hash": version.content_hash},
    )
    db.commit()
    return ok({"version_id": str(version.id), "content_hash": version.content_hash})


@router.post(
    "/content-versions/{version_id}/submit",
    response_model=Envelope[ContentVersionSubmitted],
)
def submit_content_version(
    version_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    version = require_scoped_row(
        db, ContentVersion, ctx.project.id, resource="content_version", for_update=True, id=version_id
    )
    item = require_scoped_row(db, ContentItem, ctx.project.id, resource="content_item", id=version.item_id)
    if item.current_version_id != version.id:
        raise ReviewStateError("只能提交当前内容版本")
    if version.status not in (ContentStatus.DRAFT, ContentStatus.REJECTED):
        raise ReviewStateError("当前版本不能重复提交审核")
    if not version.body.strip():
        raise ReviewStateError("版本正文为空，不能提交审核")
    target = ensure_content_transition(version.status, ContentStatus.PENDING_REVIEW)
    version.status = target
    version.submitted_by = ctx.user.id
    version.submitted_at = datetime.now(timezone.utc)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="content.submit",
        target_type="content_version",
        target_id=version.id,
        payload={"content_hash": version.content_hash},
    )
    db.commit()
    return ok({"version_id": str(version.id), "status": version.status.value, "submitted_at": version.submitted_at})


@router.get(
    "/content-versions/{version_id}/reviews",
    response_model=PagedEnvelope[ContentReviewData],
)
def list_content_reviews(
    version_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    require_scoped_row(db, ContentVersion, ctx.project.id, resource="content_version", id=version_id)
    filters = [ContentReview.project_id == ctx.project.id, ContentReview.version_id == version_id]
    total = db.scalar(select(func.count()).select_from(ContentReview).where(*filters)) or 0
    rows = db.execute(
        select(ContentReview, User.display_name)
        .outerjoin(User, User.id == ContentReview.reviewer_id)
        .where(*filters)
        .order_by(ContentReview.created_at.desc(), ContentReview.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page(
        [
            {
                "id": str(review.id),
                "version_id": str(review.version_id),
                "reviewer_id": str(review.reviewer_id),
                "reviewer_name": reviewer_name,
                "decision": review.decision.value,
                "comment": review.comment,
                "content_hash_snapshot": review.content_hash_snapshot,
                "created_at": review.created_at,
            }
            for review, reviewer_name in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post(
    "/content-versions/{version_id}/review",
    response_model=Envelope[ContentReviewCreated],
)
def review_content_version(
    version_id: uuid.UUID,
    payload: ContentReviewRequest,
    ctx: ProjectContext = Depends(require_permission("content.review")),
    db: Session = Depends(get_db),
) -> dict:
    version = require_scoped_row(
        db, ContentVersion, ctx.project.id, resource="content_version", for_update=True, id=version_id
    )
    if version.status != ContentStatus.PENDING_REVIEW:
        raise ReviewStateError("内容版本尚未提交审核或已处理")
    if not version.body:
        raise ResourceMissingError("版本正文为空，不能审批", code="empty_version")

    review = ContentReview(
        project_id=ctx.project.id,
        version_id=version.id,
        reviewer_id=ctx.user.id,
        decision=payload.decision,
        comment=payload.comment,
        content_hash_snapshot=version.content_hash,
    )
    db.add(review)
    target = (
        ContentStatus.APPROVED
        if payload.decision == ReviewDecision.APPROVED
        else ContentStatus.REJECTED
    )
    version.status = ensure_content_transition(version.status, target)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="content.review",
        target_type="content_version",
        target_id=version.id,
        payload={
            "decision": payload.decision.value,
            "content_hash_snapshot": review.content_hash_snapshot,
            "review_id": str(review.id),
        },
    )
    db.commit()
    return ok({"review_id": str(review.id), "decision": payload.decision.value})
