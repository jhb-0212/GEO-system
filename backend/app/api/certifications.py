"""项目资质：营业执照、办学许可、行业认证等，带有效期与到期提示。

到期状态不落库，读取时按 expires_on 现算，接口统一给 valid / expiring / expired，
前端只负责展示，不在前端重算一遍口径。
"""

import uuid
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope
from app.api.responses import ok
from app.core.errors import AppError
from app.db.session import get_db
from app.models import Certification
from app.schemas.certification import CertificationCreate, CertificationUpdate
from app.services.audit import record_audit
from app.services.project_scope import require_scoped_row

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/certifications",
    tags=["资质"],
    responses=COMMON_ERRORS,
)

EXPIRING_DAYS = 60


def _status(expires_on: date | None) -> tuple[str | None, int | None]:
    if expires_on is None:
        return None, None
    days_left = (expires_on - date.today()).days
    if days_left < 0:
        return "expired", days_left
    if days_left <= EXPIRING_DAYS:
        return "expiring", days_left
    return "valid", days_left


def _serialize(row: Certification) -> dict:
    status, days_left = _status(row.expires_on)
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "name": row.name,
        "category": row.category,
        "issuer": row.issuer,
        "cert_no": row.cert_no,
        "issued_on": row.issued_on,
        "expires_on": row.expires_on,
        "status": status,
        "days_left": days_left,
        "evidence_url": row.evidence_url,
        "notes": row.notes,
        "is_active": row.is_active,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("", response_model=Envelope[list])
def list_certifications(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    include_inactive: bool = False,
) -> dict:
    query = select(Certification).where(Certification.project_id == ctx.project.id)
    if not include_inactive:
        query = query.where(Certification.is_active.is_(True))
    rows = db.scalars(query.order_by(Certification.expires_on.asc().nullslast(), Certification.created_at.desc())).all()
    return ok([_serialize(row) for row in rows])


@router.post("", status_code=201, response_model=Envelope[dict])
def create_certification(
    payload: CertificationCreate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    if payload.issued_on and payload.expires_on and payload.expires_on < payload.issued_on:
        raise AppError("到期日不能早于发证日", code="certification_date_invalid")
    row = Certification(
        project_id=ctx.project.id,
        created_by=ctx.user.id,
        **payload.model_dump(),
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="certification.create",
        target_type="certification",
        target_id=row.id,
        payload={"name": row.name},
    )
    db.commit()
    return ok(_serialize(row))


@router.patch("/{certification_id}", response_model=Envelope[dict])
def update_certification(
    certification_id: uuid.UUID,
    payload: CertificationUpdate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    row = require_scoped_row(db, Certification, ctx.project.id, resource="certification", id=certification_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise AppError("没有需要更新的字段", code="empty_update")
    issued = changes.get("issued_on", row.issued_on)
    expires = changes.get("expires_on", row.expires_on)
    if issued and expires and expires < issued:
        raise AppError("到期日不能早于发证日", code="certification_date_invalid")
    for field, value in changes.items():
        setattr(row, field, value)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="certification.update",
        target_type="certification",
        target_id=row.id,
        payload={"fields": sorted(changes)},
    )
    db.commit()
    return ok(_serialize(row))


@router.delete("/{certification_id}", response_model=Envelope[dict])
def delete_certification(
    certification_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    row = require_scoped_row(db, Certification, ctx.project.id, resource="certification", id=certification_id)
    db.delete(row)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="certification.delete",
        target_type="certification",
        target_id=certification_id,
        payload={"name": row.name},
    )
    db.commit()
    return ok({"id": str(certification_id), "deleted": True})