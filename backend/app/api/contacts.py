"""项目对外渠道台账：每个渠道一条对外联系方式，标注是否对外公开。

口径边界：
- 对外「官方值」（业务电话 / 售后热线 / 企业邮箱）只维护在企业档案，本表不复制；
- 本表记录的是多渠道露面矩阵（公众号、小红书、抖音、门店电话等），可以同渠道多条；
- 唯一约束落在 (project_id, channel, value)，重复登记直接拒绝而不是静默覆盖。
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, ok
from app.core.errors import AppError
from app.db.session import get_db
from app.models import ProjectContact
from app.models.contacts import CHANNEL_LABELS
from app.schemas.project_contact import ProjectContactCreate, ProjectContactUpdate
from app.services.audit import record_audit
from app.services.project_scope import require_scoped_row

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/contacts",
    tags=["对外渠道"],
    responses=COMMON_ERRORS,
)


def _serialize(row: ProjectContact) -> dict:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "channel": row.channel,
        "channel_label": CHANNEL_LABELS.get(row.channel, row.channel),
        "value": row.value,
        "label": row.label,
        "is_public": row.is_public,
        "sort_order": row.sort_order,
        "notes": row.notes,
        "is_active": row.is_active,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("", response_model=Envelope[list])
def list_contacts(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    include_inactive: bool = False,
) -> dict:
    query = select(ProjectContact).where(ProjectContact.project_id == ctx.project.id)
    if not include_inactive:
        query = query.where(ProjectContact.is_active.is_(True))
    rows = db.scalars(
        query.order_by(ProjectContact.sort_order.asc(), ProjectContact.created_at.asc())
    ).all()
    return ok([_serialize(row) for row in rows])


@router.post("", status_code=201, response_model=Envelope[dict])
def create_contact(
    payload: ProjectContactCreate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    row = ProjectContact(
        project_id=ctx.project.id,
        created_by=ctx.user.id,
        **payload.model_dump(),
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(
            "同一渠道下这个值已经登记过，改那一条而不是再加一条",
            code="contact_duplicate",
        ) from exc
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="project_contact.create",
        target_type="project_contact",
        target_id=row.id,
        payload={"channel": row.channel, "value": row.value},
    )
    db.commit()
    return ok(_serialize(row))


@router.patch("/{contact_id}", response_model=Envelope[dict])
def update_contact(
    contact_id: uuid.UUID,
    payload: ProjectContactUpdate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    row = require_scoped_row(db, ProjectContact, ctx.project.id, resource="project_contact", id=contact_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise AppError("没有需要更新的字段", code="empty_update")
    for field, value in changes.items():
        setattr(row, field, value)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(
            "同一渠道下这个值已经登记过，改那一条而不是再加一条",
            code="contact_duplicate",
        ) from exc
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="project_contact.update",
        target_type="project_contact",
        target_id=row.id,
        payload={"fields": sorted(changes)},
    )
    db.commit()
    return ok(_serialize(row))


@router.delete("/{contact_id}", response_model=Envelope[dict])
def delete_contact(
    contact_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    row = require_scoped_row(db, ProjectContact, ctx.project.id, resource="project_contact", id=contact_id)
    db.delete(row)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="project_contact.delete",
        target_type="project_contact",
        target_id=contact_id,
        payload={"channel": row.channel, "value": row.value},
    )
    db.commit()
    return ok({"id": str(contact_id), "deleted": True})
