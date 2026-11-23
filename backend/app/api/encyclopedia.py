"""K4 百科词条接口：一个项目一份词条台账，按平台分组看进度。"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, ok
from app.db.session import get_db
from app.schemas.encyclopedia import (
    EncyclopediaEntryCreate,
    EncyclopediaEntryUpdate,
    EncyclopediaPublish,
    EncyclopediaReview,
)
from app.services.audit import record_audit
from app.services.encyclopedia import (
    create_entry,
    entry_snapshot,
    get_entry,
    list_entries,
    register_publication,
    review_entry,
    submit_entry,
    update_entry,
)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/encyclopedia-entries",
    tags=["百科词条"],
    responses=COMMON_ERRORS,
)


@router.get("", response_model=Envelope[list])
def list_route(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    return ok(list_entries(db, ctx.project.id, limit=limit))


@router.post("", status_code=201, response_model=Envelope[dict])
def create_route(
    payload: EncyclopediaEntryCreate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    entry = create_entry(
        db,
        ctx.project.id,
        title=payload.title,
        platform=payload.platform,
        body=payload.body,
        summary=payload.summary,
        references=payload.references,
        slug=payload.slug,
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="encyclopedia.create",
        target_type="encyclopedia_entry",
        target_id=entry.id,
        payload={"platform": entry.platform},
    )
    db.commit()
    return ok(entry_snapshot(entry))


@router.get("/{entry_id}", response_model=Envelope[dict])
def get_route(
    entry_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
) -> dict:
    return ok(entry_snapshot(get_entry(db, ctx.project.id, entry_id)))


@router.patch("/{entry_id}", response_model=Envelope[dict])
def update_route(
    entry_id: uuid.UUID,
    payload: EncyclopediaEntryUpdate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    entry = get_entry(db, ctx.project.id, entry_id)
    changes = payload.model_dump(exclude_unset=True)
    update_entry(db, entry, changes)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="encyclopedia.update",
        target_type="encyclopedia_entry",
        target_id=entry.id,
        payload={"fields": sorted(changes)},
    )
    db.commit()
    return ok(entry_snapshot(entry))


@router.post("/{entry_id}/submit", response_model=Envelope[dict])
def submit_route(
    entry_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    entry = get_entry(db, ctx.project.id, entry_id)
    submit_entry(db, entry)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="encyclopedia.submit",
        target_type="encyclopedia_entry",
        target_id=entry.id,
        payload={"references": len(entry.references or [])},
    )
    db.commit()
    return ok(entry_snapshot(entry))


@router.post("/{entry_id}/review", response_model=Envelope[dict])
def review_route(
    entry_id: uuid.UUID,
    payload: EncyclopediaReview,
    ctx: ProjectContext = Depends(require_permission("content.review")),
    db: Session = Depends(get_db),
) -> dict:
    entry = get_entry(db, ctx.project.id, entry_id)
    review_entry(
        db, entry, approve=payload.approve, reviewer_id=ctx.user.id, note=payload.note
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="encyclopedia.review",
        target_type="encyclopedia_entry",
        target_id=entry.id,
        payload={"approve": payload.approve},
    )
    db.commit()
    return ok(entry_snapshot(entry))


@router.post("/{entry_id}/publication", response_model=Envelope[dict])
def publication_route(
    entry_id: uuid.UUID,
    payload: EncyclopediaPublish,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    entry = get_entry(db, ctx.project.id, entry_id)
    register_publication(db, entry, published_url=payload.published_url)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="encyclopedia.publication",
        target_type="encyclopedia_entry",
        target_id=entry.id,
        payload={"platform": entry.platform},
    )
    db.commit()
    return ok(entry_snapshot(entry))
