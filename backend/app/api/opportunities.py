"""机会中心：证据驱动的运营任务。

机会只负责把引用缺口、事实纠错和网站修复整理成可指派任务；
内容生产、审核和发布仍走既有内容链，不允许 AI 自动生成后直接发布。
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, OpportunityData, PagedEnvelope, ok, ok_page
from app.services.opportunity_listing import (
    opportunity_row as _get_opportunity,
    page_opportunities as _page_opportunities,
    payload_one as _opportunity_data,
    payloads as _opportunity_payloads,
)
from app.services.references import require_member, require_project_row_id
from app.services.state_machine import ensure_opportunity_transition
from app.core.errors import AppError
from app.db.session import get_db
from app.models import (
    ContentItem,
    ContentPlan,
    MonitoringSample,
    Opportunity,
    PublishTask,
    Question,
)
from app.models.enums import OpportunityGapType, OpportunityStatus
from app.schemas import OpportunityCreate, OpportunityUpdate
from app.schemas.opportunities import OpportunityScoreFactors, OpportunityScoreWeights
from app.services.audit import record_audit
from app.services.opportunities import score_opportunity

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/opportunities",
    tags=["机会中心"],
    responses=COMMON_ERRORS,
)


@router.get("", response_model=PagedEnvelope[OpportunityData])
def list_opportunities(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    status: OpportunityStatus | None = None,
    gap_type: OpportunityGapType | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    filters = [Opportunity.project_id == ctx.project.id]
    if status is not None:
        filters.append(Opportunity.status == status)
    if gap_type:
        filters.append(Opportunity.gap_type == gap_type)
    rows, total = _page_opportunities(db, filters, page=page, page_size=page_size)
    return ok_page(
        _opportunity_payloads(db, rows),
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", status_code=201, response_model=Envelope[OpportunityData])
def create_opportunity(
    payload: OpportunityCreate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    require_project_row_id(
        db, Question, ctx.project.id, payload.question_id,
        label="问题", code="question_missing",
    )
    require_project_row_id(
        db, MonitoringSample, ctx.project.id, payload.sample_id,
        label="样本", code="sample_missing",
    )
    require_member(db, ctx.project.id, payload.owner_id)
    factors, weights, priority = score_opportunity(payload.score_factors, payload.score_weights)
    row = Opportunity(
        project_id=ctx.project.id,
        title=payload.title,
        gap_type=payload.gap_type,
        question_id=payload.question_id,
        sample_id=payload.sample_id,
        evidence_refs=payload.evidence_refs,
        score_factors=factors,
        score_weights=weights,
        priority_score=priority,
        owner_id=payload.owner_id,
        notes=payload.notes,
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="opportunity.create",
        target_type="opportunity",
        target_id=row.id,
        payload={
            "title": row.title,
            "gap_type": row.gap_type.value,
            "priority_score": float(priority),
            "evidence_refs": len(payload.evidence_refs),
        },
    )
    db.commit()
    return ok(_opportunity_data(db, row))


@router.patch("/{opportunity_id}", response_model=Envelope[OpportunityData])
def update_opportunity(
    opportunity_id: uuid.UUID,
    payload: OpportunityUpdate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    row = _get_opportunity(db, ctx.project.id, opportunity_id, for_update=True)
    changed: list[str] = []

    if "status" in payload.model_fields_set:
        if payload.status is None:
            raise AppError("机会状态不能为空", code="invalid_opportunity_status")
        row.status = ensure_opportunity_transition(row.status, payload.status)
        changed.append("status")

    if "owner_id" in payload.model_fields_set:
        require_member(db, ctx.project.id, payload.owner_id)
        row.owner_id = payload.owner_id
        changed.append("owner_id")

    if "score_factors" in payload.model_fields_set or "score_weights" in payload.model_fields_set:
        factors = payload.score_factors or OpportunityScoreFactors(**row.score_factors)
        weights = payload.score_weights or OpportunityScoreWeights(**row.score_weights)
        raw, weight_values, priority = score_opportunity(factors, weights)
        row.score_factors = raw
        row.score_weights = weight_values
        row.priority_score = priority
        changed.extend(["score_factors", "score_weights", "priority_score"])

    for field, target, label, code in (
        ("linked_content_plan_id", ContentPlan, "内容计划", "plan_missing"),
        ("linked_content_item_id", ContentItem, "内容", "content_item_missing"),
        ("linked_publish_task_id", PublishTask, "发布任务", "publish_task_missing"),
    ):
        if field in payload.model_fields_set:
            value = getattr(payload, field)
            require_project_row_id(
                db, target, ctx.project.id, value, label=label, code=code
            )
            setattr(row, field, value)
            changed.append(field)

    if "notes" in payload.model_fields_set:
        row.notes = payload.notes
        changed.append("notes")

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="opportunity.update",
        target_type="opportunity",
        target_id=row.id,
        payload={
            "changed": changed,
            "status": row.status.value,
            "priority_score": float(row.priority_score),
        },
    )
    db.commit()
    return ok(_opportunity_data(db, row))
