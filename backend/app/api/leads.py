"""线索接口：只有 lead.read / lead.write 能力能进来。

招生/客服（lead_ops）只持有这两项能力，因此监测、证据、内容、发布、渠道接口对他们一律 403。
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import ok
from app.db.session import get_db
from app.models import Lead
from app.models.enums import EnrollmentStatus
from app.schemas import LeadCreate
from app.services.audit import record_audit

router = APIRouter(prefix="/api/v1/projects/{project_id}/leads", tags=["线索"])

MAX_PAGE_SIZE = 200


@router.get("")
def list_leads(
    ctx: ProjectContext = Depends(require_permission("lead.read")),
    db: Session = Depends(get_db),
    limit: int = 50,
) -> dict:
    rows = db.scalars(
        select(Lead)
        .where(Lead.project_id == ctx.project.id)
        .order_by(Lead.created_at.desc())
        .limit(min(limit, MAX_PAGE_SIZE))
    ).all()
    return ok(
        [
            {
                "id": str(row.id),
                "contact_name": row.contact_name,
                "contact_phone": row.contact_phone,
                "contact_wechat": row.contact_wechat,
                "interested_course": row.interested_course,
                "enrollment_status": row.enrollment_status,
            }
            for row in rows
        ]
    )


@router.post("", status_code=201)
def create_lead(
    payload: LeadCreate,
    ctx: ProjectContext = Depends(require_permission("lead.write")),
    db: Session = Depends(get_db),
) -> dict:
    lead = Lead(
        project_id=ctx.project.id,
        contact_name=payload.contact_name,
        contact_phone=payload.contact_phone,
        contact_wechat=payload.contact_wechat,
        interested_course=payload.interested_course,
        lead_source=payload.lead_source,
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
        payload={"lead_source": payload.lead_source},
    )
    db.commit()
    return ok({"id": str(lead.id)})
