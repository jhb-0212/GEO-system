"""Project-scoped citation lookup and manual classification."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    Envelope,
    MonitoringCitationData,
    PagedEnvelope,
    UnknownDomainData,
    ok,
    ok_page,
)
from app.core.errors import ReviewStateError
from app.db.session import get_db
from app.models import Channel, MonitoringCitation
from app.models.enums import CitationReviewStatus
from app.schemas.review import CitationReview
from app.services.audit import record_audit
from app.services.project_scope import require_scoped_row

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/citations",
    tags=["引用复核"],
    responses=COMMON_ERRORS,
)


def _payload(row: MonitoringCitation) -> dict:
    return {
        "id": str(row.id),
        "sample_id": str(row.sample_id),
        "raw_url": row.raw_url,
        "normalized_url": row.normalized_url,
        "domain": row.domain,
        "channel_id": str(row.channel_id) if row.channel_id else None,
        "is_brand_related": row.is_brand_related,
        "review_status": row.review_status.value,
        "review_note": row.review_note,
    }


@router.get("", response_model=PagedEnvelope[MonitoringCitationData])
def list_citations(
    ctx: ProjectContext = Depends(require_permission("monitoring.read")),
    db: Session = Depends(get_db),
    review_status: CitationReviewStatus | None = None,
    domain: str | None = Query(None, max_length=255),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    filters = [MonitoringCitation.project_id == ctx.project.id]
    if review_status is not None:
        filters.append(MonitoringCitation.review_status == review_status)
    if domain is not None:
        filters.append(MonitoringCitation.domain == domain)
    total = db.scalar(select(func.count()).select_from(MonitoringCitation).where(*filters)) or 0
    rows = db.scalars(
        select(MonitoringCitation)
        .where(*filters)
        .order_by(MonitoringCitation.created_at.desc(), MonitoringCitation.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page([_payload(row) for row in rows], page=page, page_size=page_size, total=total)


@router.get("/unknown-domains", response_model=PagedEnvelope[UnknownDomainData])
def unknown_domains(
    ctx: ProjectContext = Depends(require_permission("monitoring.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    filters = [
        MonitoringCitation.project_id == ctx.project.id,
        MonitoringCitation.channel_id.is_(None),
        MonitoringCitation.domain.is_not(None),
    ]
    total = db.scalar(
        select(func.count(func.distinct(MonitoringCitation.domain))).where(*filters)
    ) or 0
    rows = db.execute(
        select(MonitoringCitation.domain, func.count(MonitoringCitation.id))
        .where(*filters)
        .group_by(MonitoringCitation.domain)
        .order_by(func.count(MonitoringCitation.id).desc(), MonitoringCitation.domain)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page(
        [{"domain": domain, "citation_count": count} for domain, count in rows],
        page=page, page_size=page_size, total=total,
    )


@router.patch("/{citation_id}", response_model=Envelope[MonitoringCitationData])
def review_citation(
    citation_id: uuid.UUID,
    payload: CitationReview,
    ctx: ProjectContext = Depends(require_permission("evidence.review")),
    db: Session = Depends(get_db),
) -> dict:
    if payload.review_status not in (
        CitationReviewStatus.MANUAL_CONFIRMED,
        CitationReviewStatus.MANUAL_REJECTED,
    ):
        raise ReviewStateError("人工复核只能确认或驳回")
    row = require_scoped_row(
        db, MonitoringCitation, ctx.project.id, resource="monitoring_citation", for_update=True, id=citation_id
    )
    if payload.channel_id is not None:
        require_scoped_row(db, Channel, ctx.project.id, resource="channel", id=payload.channel_id)
    row.review_status = payload.review_status
    row.is_brand_related = payload.is_brand_related if payload.review_status == CitationReviewStatus.MANUAL_CONFIRMED else False
    if "channel_id" in payload.model_fields_set:
        row.channel_id = payload.channel_id
    row.review_note = payload.note
    row.reviewed_by = ctx.user.id
    row.reviewed_at = datetime.now(timezone.utc)
    record_audit(
        db, project_id=ctx.project.id, actor_id=ctx.user.id,
        action="monitoring.citation_review", target_type="monitoring_citation", target_id=row.id,
        payload={"review_status": row.review_status.value, "is_brand_related": row.is_brand_related},
    )
    db.commit()
    return ok(_payload(row))
