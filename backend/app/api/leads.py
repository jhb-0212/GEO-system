"""线索接口：只有 lead.read / lead.write 能力能进来。

招生/客服（lead_ops）只持有这两项能力，因此监测、证据、内容、发布、渠道接口对他们一律 403。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    Envelope,
    LeadCreated,
    LeadData,
    PagedEnvelope,
    ok,
    ok_page,
)
from app.core.errors import ResourceMissingError
from app.db.session import get_db
from app.models import AiEngine, Channel, Lead, Question
from app.models.enums import EnrollmentStatus
from app.schemas import LeadCreate
from app.services.audit import record_audit

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/leads",
    tags=["线索"],
    responses=COMMON_ERRORS,
)


def _require_project_ref(db: Session, model, value, project_id, label: str) -> None:
    """归因外键必须指向当前项目的题目/渠道，避免跨项目串数。"""
    if value is None:
        return
    row = db.scalar(
        select(model.id).where(model.id == value, model.project_id == project_id)
    )
    if row is None:
        raise ResourceMissingError(f"{label}不存在或不属于当前项目")


def _require_engine(db: Session, value) -> None:
    if value is None:
        return
    if db.scalar(select(AiEngine.id).where(AiEngine.id == value)) is None:
        raise ResourceMissingError("引擎不存在")


@router.get("", response_model=PagedEnvelope[LeadData])
def list_leads(
    ctx: ProjectContext = Depends(require_permission("lead.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
) -> dict:
    total = (
        db.scalar(
            select(func.count()).select_from(Lead).where(Lead.project_id == ctx.project.id)
        )
        or 0
    )
    rows = db.scalars(
        select(Lead)
        .where(Lead.project_id == ctx.project.id)
        .order_by(Lead.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page(
        [
            {
                "id": str(row.id),
                "contact_name": row.contact_name,
                "contact_phone": row.contact_phone,
                "contact_wechat": row.contact_wechat,
                "interested_course": row.interested_course,
                "enrollment_status": row.enrollment_status,
                "lead_source": row.lead_source,
                "source_question_id": str(row.source_question_id) if row.source_question_id else None,
                "source_channel_id": str(row.source_channel_id) if row.source_channel_id else None,
                "source_engine_id": str(row.source_engine_id) if row.source_engine_id else None,
                "landing_url": row.landing_url,
                "utm_campaign": row.utm_campaign,
            }
            for row in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", status_code=201, response_model=Envelope[LeadCreated])
def create_lead(
    payload: LeadCreate,
    ctx: ProjectContext = Depends(require_permission("lead.write")),
    db: Session = Depends(get_db),
) -> dict:
    _require_project_ref(db, Question, payload.source_question_id, ctx.project.id, "题目")
    _require_project_ref(db, Channel, payload.source_channel_id, ctx.project.id, "渠道")
    _require_engine(db, payload.source_engine_id)
    lead = Lead(
        project_id=ctx.project.id,
        contact_name=payload.contact_name,
        contact_phone=payload.contact_phone,
        contact_wechat=payload.contact_wechat,
        interested_course=payload.interested_course,
        lead_source=payload.lead_source,
        source_question_id=payload.source_question_id,
        source_channel_id=payload.source_channel_id,
        source_engine_id=payload.source_engine_id,
        landing_url=payload.landing_url,
        utm_campaign=payload.utm_campaign,
        note=payload.note,
        enrollment_status=EnrollmentStatus.UNKNOWN,
        owner_id=ctx.user.id,
    )
    db.add(lead)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="lead.create",
        target_type="lead",
        target_id=lead.id,
        payload={
            "lead_source": payload.lead_source,
            "source_question_id": str(payload.source_question_id) if payload.source_question_id else None,
            "source_channel_id": str(payload.source_channel_id) if payload.source_channel_id else None,
            "source_engine_id": str(payload.source_engine_id) if payload.source_engine_id else None,
            "utm_campaign": payload.utm_campaign,
        },
    )
    db.commit()
    return ok({"id": str(lead.id)})
