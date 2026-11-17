"""竞品台账：项目内竞品实体，用于答案提及归因与 Share of Voice，不把竞品名写进自由文本。"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
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
from app.core.errors import AppError, ResourceMissingError
from app.db.session import get_db
from app.models import Competitor
from app.schemas import CompetitorCreate, CompetitorUpdate
from app.services.audit import record_audit

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/competitors",
    tags=["竞品"],
    responses=COMMON_ERRORS,
)


def _competitor_data(competitor: Competitor) -> dict:
    return {
        "id": str(competitor.id),
        "name": competitor.name,
        "domain": competitor.domain,
        "is_active": competitor.is_active,
        "notes": competitor.notes,
        "created_at": competitor.created_at,
        "updated_at": competitor.updated_at,
    }


def _get_competitor(
    db: Session,
    project_id: uuid.UUID,
    competitor_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> Competitor:
    query = select(Competitor).where(
        Competitor.project_id == project_id,
        Competitor.id == competitor_id,
    )
    if for_update:
        query = query.with_for_update()
    competitor = db.scalar(query)
    if competitor is None:
        raise ResourceMissingError("竞品不存在", code="competitor_missing")
    return competitor


@router.get("", response_model=PagedEnvelope[CompetitorData])
def list_competitors(
    ctx: ProjectContext = Depends(require_permission("monitoring.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
) -> dict:
    total = (
        db.scalar(
            select(func.count())
            .select_from(Competitor)
            .where(Competitor.project_id == ctx.project.id)
        )
        or 0
    )
    rows = db.scalars(
        select(Competitor)
        .where(Competitor.project_id == ctx.project.id)
        .order_by(Competitor.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
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
    existing = db.scalar(
        select(Competitor).where(
            Competitor.project_id == ctx.project.id,
            Competitor.name == payload.name,
        )
    )
    if existing is not None:
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
        existing = db.scalar(
            select(Competitor).where(
                Competitor.project_id == ctx.project.id,
                Competitor.name == changes["name"],
                Competitor.id != competitor.id,
            )
        )
        if existing is not None:
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
