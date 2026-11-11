"""内容接口：写正文要 content.write，审批要 content.review。

审核人员没有 content.write，改正文一律 403；审批必须写 content_hash_snapshot 留痕。
"""

import hashlib
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    ContentBodyUpdated,
    ContentItemCreated,
    ContentReviewCreated,
    ContentVersionCreated,
    Envelope,
    ok,
)
from app.core.errors import ResourceMissingError
from app.db.session import get_db
from app.models import ContentItem, ContentReview, ContentVersion
from app.models.enums import ContentStatus, ReviewDecision
from app.schemas import (
    ContentBodyUpdate,
    ContentItemCreate,
    ContentReviewRequest,
    ContentVersionCreate,
)
from app.services.audit import record_audit
from app.services.project_scope import require_scoped_row

router = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["内容与审核"],
    responses=COMMON_ERRORS,
)


def _content_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@router.post("/contents", status_code=201, response_model=Envelope[ContentItemCreated])
def create_content_item(
    payload: ContentItemCreate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
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
    item = require_scoped_row(db, ContentItem, ctx.project.id, resource="content_item", id=item_id)
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
        db, ContentVersion, ctx.project.id, resource="content_version", id=version_id
    )
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
        db, ContentVersion, ctx.project.id, resource="content_version", id=version_id
    )
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
    version.status = (
        ContentStatus.APPROVED
        if payload.decision == ReviewDecision.APPROVED
        else ContentStatus.REJECTED
    )
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
