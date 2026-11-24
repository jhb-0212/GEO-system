"""竞品台账：项目内竞品实体，用于答案提及归因与 Share of Voice，不把竞品名写进自由文本。"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    CompetitorCreated,
    CompetitorData,
    Envelope,
    PagedEnvelope,
    ok,
    ok_page,
)
from app.core.errors import AppError, ConflictError, ResourceMissingError
from app.db.session import get_db
from app.models import Competitor
from app.schemas import CompetitorCreate, CompetitorDeleted, CompetitorUpdate
from app.services.audit import record_audit
from app.services.competitor_registry import (
    competitor_payload as _competitor_data,
    competitor_row as _get_competitor,
    name_exists,
    page_competitors,
    reference_counts as _competitor_reference_counts,
)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/competitors",
    tags=["竞品"],
    responses=COMMON_ERRORS,
)


@router.get("", response_model=PagedEnvelope[CompetitorData])
def list_competitors(
    ctx: ProjectContext = Depends(require_permission("monitoring.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
) -> dict:
    rows, total = page_competitors(db, ctx.project.id, page=page, page_size=page_size)
    return ok_page(
        [_competitor_data(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", status_code=201, response_model=Envelope[CompetitorCreated])
def create_competitor(
    payload: CompetitorCreate,
    ctx: ProjectContext = Depends(require_permission("competitor.write")),
    db: Session = Depends(get_db),
) -> dict:
    if name_exists(db, ctx.project.id, payload.name):
        raise AppError("竞品名称已存在", code="competitor_conflict")

    competitor = Competitor(
        project_id=ctx.project.id,
        name=payload.name,
        domain=payload.domain,
        is_active=payload.is_active,
        notes=payload.notes,
    )
    db.add(competitor)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise AppError("竞品名称已存在", code="competitor_conflict") from exc

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="competitor.create",
        target_type="competitor",
        target_id=competitor.id,
        payload={"name": competitor.name, "is_active": competitor.is_active},
    )
    db.commit()
    return ok({"id": str(competitor.id)})


@router.patch("/{competitor_id}", response_model=Envelope[CompetitorData])
def update_competitor(
    competitor_id: uuid.UUID,
    payload: CompetitorUpdate,
    ctx: ProjectContext = Depends(require_permission("competitor.write")),
    db: Session = Depends(get_db),
) -> dict:
    competitor = _get_competitor(db, ctx.project.id, competitor_id, for_update=True)
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes and (changes["name"] is None or not str(changes["name"]).strip()):
        raise AppError("name 不能为空", code="invalid_competitor_field")
    if "name" in changes and changes["name"] != competitor.name:
        if name_exists(db, ctx.project.id, changes["name"], exclude_id=competitor.id):
            raise AppError("竞品名称已存在", code="competitor_conflict")

    audit_changes: dict[str, object] = {}
    try:
        for key, value in changes.items():
            setattr(competitor, key, value)
            audit_changes[key] = value
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise AppError("竞品名称已存在", code="competitor_conflict") from exc

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="competitor.update",
        target_type="competitor",
        target_id=competitor.id,
        payload={"changes": audit_changes},
    )
    db.commit()
    return ok(_competitor_data(competitor))


@router.delete("/{competitor_id}", response_model=Envelope[CompetitorDeleted])
def delete_competitor(
    competitor_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("competitor.write")),
    db: Session = Depends(get_db),
) -> dict:
    competitor = _get_competitor(db, ctx.project.id, competitor_id, for_update=True)
    mentions, citations = _competitor_reference_counts(
        db, ctx.project.id, competitor.id
    )
    if mentions or citations:
        raise ConflictError(
            f"已有 {mentions} 条历史提及、{citations} 条引用关联，不能删除；请改为停用。",
            code="competitor_in_use",
        )

    name = competitor.name
    domain = competitor.domain
    db.delete(competitor)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="competitor.delete",
        target_type="competitor",
        target_id=competitor_id,
        payload={"name": name, "domain": domain},
    )
    db.commit()
    return ok({"id": str(competitor_id), "deleted": True})
