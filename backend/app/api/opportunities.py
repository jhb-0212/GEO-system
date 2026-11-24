"""机会中心：证据驱动的运营任务。

机会只负责把引用缺口、事实纠错和网站修复整理成可指派任务；
内容生产、审核和发布仍走既有内容链，不允许 AI 自动生成后直接发布。
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, OpportunityData, PagedEnvelope, ok, ok_page
from app.services.state_machine import ensure_opportunity_transition
from app.core.errors import AppError, ResourceMissingError
from app.db.session import get_db
from app.models import (
    ContentItem,
    ContentPlan,
    MonitoringSample,
    Opportunity,
    ProjectMember,
    PublishTask,
    Question,
    User,
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


def _get_opportunity(
    db: Session,
    project_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> Opportunity:
    query = select(Opportunity).where(
        Opportunity.project_id == project_id,
        Opportunity.id == opportunity_id,
    )
    if for_update:
        query = query.with_for_update()
    row = db.scalar(query)
    if row is None:
        raise ResourceMissingError("机会不存在", code="opportunity_missing")
    return row


def _ensure_question(db: Session, project_id: uuid.UUID, question_id: uuid.UUID | None) -> None:
    if question_id is None:
        return
    if db.scalar(select(Question.id).where(Question.project_id == project_id, Question.id == question_id)) is None:
        raise ResourceMissingError("问题不存在", code="question_missing")


def _ensure_sample(db: Session, project_id: uuid.UUID, sample_id: uuid.UUID | None) -> None:
    if sample_id is None:
        return
    if db.scalar(
        select(MonitoringSample.id).where(
            MonitoringSample.project_id == project_id,
            MonitoringSample.id == sample_id,
        )
    ) is None:
        raise ResourceMissingError("样本不存在", code="sample_missing")


def _ensure_owner(db: Session, project_id: uuid.UUID, owner_id: uuid.UUID | None) -> None:
    if owner_id is None:
        return
    member = db.scalar(
        select(ProjectMember.id).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == owner_id,
            ProjectMember.is_active.is_(True),
        )
    )
    if member is None:
        raise ResourceMissingError("负责人不是当前项目的有效成员", code="owner_missing")


def _ensure_content_plan(db: Session, project_id: uuid.UUID, plan_id: uuid.UUID | None) -> None:
    if plan_id is None:
        return
    if db.scalar(select(ContentPlan.id).where(ContentPlan.project_id == project_id, ContentPlan.id == plan_id)) is None:
        raise ResourceMissingError("内容计划不存在", code="plan_missing")


def _ensure_content_item(db: Session, project_id: uuid.UUID, item_id: uuid.UUID | None) -> None:
    if item_id is None:
        return
    if db.scalar(select(ContentItem.id).where(ContentItem.project_id == project_id, ContentItem.id == item_id)) is None:
        raise ResourceMissingError("内容不存在", code="content_item_missing")


def _ensure_publish_task(db: Session, project_id: uuid.UUID, task_id: uuid.UUID | None) -> None:
    if task_id is None:
        return
    if db.scalar(select(PublishTask.id).where(PublishTask.project_id == project_id, PublishTask.id == task_id)) is None:
        raise ResourceMissingError("发布任务不存在", code="publish_task_missing")


def _opportunity_data(db: Session, row: Opportunity) -> dict:
    owner_name = None
    if row.owner_id is not None:
        owner_name = db.scalar(select(User.display_name).where(User.id == row.owner_id))
    return {
        "id": str(row.id),
        "title": row.title,
        "gap_type": row.gap_type.value,
        "status": row.status.value,
        "question_id": str(row.question_id) if row.question_id else None,
        "sample_id": str(row.sample_id) if row.sample_id else None,
        "evidence_refs": row.evidence_refs or [],
        "score_factors": row.score_factors,
        "score_weights": row.score_weights,
        "priority_score": float(row.priority_score),
        "owner_id": str(row.owner_id) if row.owner_id else None,
        "owner_name": owner_name,
        "linked_content_plan_id": str(row.linked_content_plan_id) if row.linked_content_plan_id else None,
        "linked_content_item_id": str(row.linked_content_item_id) if row.linked_content_item_id else None,
        "linked_publish_task_id": str(row.linked_publish_task_id) if row.linked_publish_task_id else None,
        "notes": row.notes,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


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
    total = int(db.scalar(select(func.count()).select_from(Opportunity).where(*filters)) or 0)
    rows = db.scalars(
        select(Opportunity)
        .where(*filters)
        .order_by(Opportunity.priority_score.desc(), Opportunity.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page(
        [_opportunity_data(db, row) for row in rows],
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
    _ensure_question(db, ctx.project.id, payload.question_id)
    _ensure_sample(db, ctx.project.id, payload.sample_id)
    _ensure_owner(db, ctx.project.id, payload.owner_id)
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
        _ensure_owner(db, ctx.project.id, payload.owner_id)
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

    for field, ensure in (
        ("linked_content_plan_id", _ensure_content_plan),
        ("linked_content_item_id", _ensure_content_item),
        ("linked_publish_task_id", _ensure_publish_task),
    ):
        if field in payload.model_fields_set:
            value = getattr(payload, field)
            ensure(db, ctx.project.id, value)
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
