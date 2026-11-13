"""关键词接口：复用 question.read / question.write；DELETE 只做软删。

本轮不建立题目↔关键词直连，关键词只通过 content_version_keywords 关联内容版本。
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    Envelope,
    KeywordData,
    PagedEnvelope,
    ok,
    ok_page,
)
from app.core.errors import AppError, ConflictError, ResourceMissingError
from app.db.session import get_db
from app.models import ContentVersionKeyword, Keyword
from app.schemas import KeywordCreate, KeywordUpdate
from app.services.audit import record_audit

router = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["关键词"],
    responses=COMMON_ERRORS,
)


def _require_keyword(
    db: Session,
    project_id: uuid.UUID,
    keyword_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> Keyword:
    query = select(Keyword).where(
        Keyword.id == keyword_id,
        Keyword.project_id == project_id,
    )
    if for_update:
        query = query.with_for_update()
    row = db.scalar(query)
    if row is None:
        raise ResourceMissingError("关键词不存在或不属于当前项目", code="keyword_missing")
    return row


def _content_version_count(db: Session, project_id: uuid.UUID, keyword_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(ContentVersionKeyword)
            .where(
                ContentVersionKeyword.project_id == project_id,
                ContentVersionKeyword.keyword_id == keyword_id,
            )
        )
        or 0
    )


def _keyword_data(db: Session, row: Keyword) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "category": row.category,
        "priority": row.priority,
        "is_active": row.is_active,
        "notes": row.notes,
        "content_version_count": _content_version_count(db, row.project_id, row.id),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/keywords", response_model=PagedEnvelope[KeywordData])
def list_keywords(
    ctx: ProjectContext = Depends(require_permission("question.read")),
    db: Session = Depends(get_db),
    category: str | None = Query(None, max_length=64, description="按分类精确筛选"),
    is_active: bool | None = Query(None, description="按启停筛选"),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
) -> dict:
    filters = [Keyword.project_id == ctx.project.id]
    if category is not None:
        filters.append(Keyword.category == category)
    if is_active is not None:
        filters.append(Keyword.is_active == is_active)

    total = db.scalar(select(func.count()).select_from(Keyword).where(*filters)) or 0
    rows = db.execute(
        select(Keyword, func.count(ContentVersionKeyword.id))
        .outerjoin(
            ContentVersionKeyword,
            (ContentVersionKeyword.project_id == Keyword.project_id)
            & (ContentVersionKeyword.keyword_id == Keyword.id),
        )
        .where(*filters)
        .group_by(Keyword.id)
        .order_by(Keyword.name, Keyword.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page(
        [
            {
                "id": str(row.id),
                "name": row.name,
                "category": row.category,
                "priority": row.priority,
                "is_active": row.is_active,
                "notes": row.notes,
                "content_version_count": count,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
            for row, count in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/keywords", status_code=201, response_model=Envelope[KeywordData])
def create_keyword(
    payload: KeywordCreate,
    ctx: ProjectContext = Depends(require_permission("question.write")),
    db: Session = Depends(get_db),
) -> dict:
    existing = db.scalar(
        select(Keyword.id).where(
            Keyword.project_id == ctx.project.id,
            Keyword.name == payload.name,
        )
    )
    if existing is not None:
        raise ConflictError("关键词名称已存在", code="keyword_name_conflict")

    keyword = Keyword(
        project_id=ctx.project.id,
        name=payload.name,
        category=payload.category,
        priority=payload.priority,
        is_active=payload.is_active,
        notes=payload.notes,
    )
    db.add(keyword)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("关键词名称已存在", code="keyword_name_conflict") from exc
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="keyword.create",
        target_type="keyword",
        target_id=keyword.id,
        payload={"name": keyword.name, "category": keyword.category},
    )
    db.commit()
    db.refresh(keyword)
    return ok(_keyword_data(db, keyword))


@router.patch("/keywords/{keyword_id}", response_model=Envelope[KeywordData])
def update_keyword(
    keyword_id: uuid.UUID,
    payload: KeywordUpdate,
    ctx: ProjectContext = Depends(require_permission("question.write")),
    db: Session = Depends(get_db),
) -> dict:
    keyword = _require_keyword(db, ctx.project.id, keyword_id, for_update=True)
    changes = payload.model_dump(exclude_unset=True)
    for field in ("name", "priority", "is_active"):
        if field in changes and changes[field] is None:
            raise AppError(f"{field} 不能为空", code="invalid_keyword_field")

    if "name" in changes and changes["name"] != keyword.name:
        existing = db.scalar(
            select(Keyword.id).where(
                Keyword.project_id == ctx.project.id,
                Keyword.name == changes["name"],
                Keyword.id != keyword.id,
            )
        )
        if existing is not None:
            raise ConflictError("关键词名称已存在", code="keyword_name_conflict")

    for field, value in changes.items():
        setattr(keyword, field, value)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("关键词名称已存在", code="keyword_name_conflict") from exc

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="keyword.update",
        target_type="keyword",
        target_id=keyword.id,
        payload={
            key: (value.value if hasattr(value, "value") else value)
            for key, value in changes.items()
        },
    )
    db.commit()
    return ok(_keyword_data(db, keyword))


@router.delete("/keywords/{keyword_id}", response_model=Envelope[KeywordData])
def delete_keyword(
    keyword_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("question.write")),
    db: Session = Depends(get_db),
) -> dict:
    keyword = _require_keyword(db, ctx.project.id, keyword_id, for_update=True)
    was_active = keyword.is_active
    keyword.is_active = False
    if was_active:
        record_audit(
            db,
            project_id=ctx.project.id,
            actor_id=ctx.user.id,
            action="keyword.delete",
            target_type="keyword",
            target_id=keyword.id,
            payload={"soft_deleted": True, "name": keyword.name},
        )
    db.commit()
    return ok(_keyword_data(db, keyword))
