"""FAQ 管理接口：内部编辑走 content.read / content.write，公开只读另走 public 路由。"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    Envelope,
    FaqCreated,
    FaqData,
    PagedEnvelope,
    ok,
    ok_page,
)
from app.core.errors import AppError
from app.db.session import get_db
from app.models import Faq
from app.models.enums import FaqStatus
from app.schemas import FaqCreate, FaqUpdate
from app.services.audit import record_audit
from app.services.project_scope import require_scoped_row

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/faqs",
    tags=["FAQ"],
    responses=COMMON_ERRORS,
)


def _serialize(row: Faq) -> dict:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "question": row.question,
        "answer": row.answer,
        "category": row.category,
        "status": row.status,
        "sort_order": row.sort_order,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("", response_model=PagedEnvelope[FaqData])
def list_faqs(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
    status: FaqStatus | None = Query(default=None, description="按状态筛选"),
    category: str | None = Query(default=None, max_length=64, description="按分类筛选"),
) -> dict:
    base = select(Faq).where(Faq.project_id == ctx.project.id)
    if status is not None:
        base = base.where(Faq.status == status)
    if category:
        base = base.where(Faq.category == category)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(Faq.sort_order, Faq.created_at)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page([_serialize(row) for row in rows], page=page, page_size=page_size, total=total)


@router.post("", status_code=201, response_model=Envelope[FaqCreated])
def create_faq(
    payload: FaqCreate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    row = Faq(
        project_id=ctx.project.id,
        question=payload.question,
        answer=payload.answer,
        category=payload.category,
        status=payload.status,
        sort_order=payload.sort_order,
        created_by=ctx.user.id,
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="faq.create",
        target_type="faq",
        target_id=row.id,
        payload={"status": row.status, "question": row.question},
    )
    db.commit()
    return ok({"id": str(row.id)})


@router.patch("/{faq_id}", response_model=Envelope[FaqData])
def update_faq(
    faq_id: uuid.UUID,
    payload: FaqUpdate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    row = require_scoped_row(db, Faq, ctx.project.id, resource="faq", id=faq_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise AppError("没有需要更新的字段", code="empty_update")
    for field, value in changes.items():
        setattr(row, field, value)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="faq.update",
        target_type="faq",
        target_id=row.id,
        payload={"fields": sorted(changes)},
    )
    db.commit()
    return ok(_serialize(row))


@router.delete("/{faq_id}", response_model=Envelope[FaqData])
def delete_faq(
    faq_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    row = require_scoped_row(db, Faq, ctx.project.id, resource="faq", id=faq_id, for_update=True)
    was_published = row.status == FaqStatus.PUBLISHED
    row.status = FaqStatus.UNPUBLISHED
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="faq.delete",
        target_type="faq",
        target_id=row.id,
        payload={"soft_deleted": True, "was_published": was_published, "question": row.question},
    )
    db.commit()
    return ok(_serialize(row))
