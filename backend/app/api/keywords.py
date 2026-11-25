"""关键词接口：复用 question.read / question.write；DELETE 只做软删。

题目级关键词走 question_keywords，版本级关键词走 content_version_keywords；两者并存，按粒度使用，不互相替代。
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete
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
from app.models import ContentVersionKeyword, Keyword, QuestionKeyword
from app.schemas import KeywordCreate, KeywordUpdate
from app.services.audit import record_audit
from app.services.keyword_links import (
    add_links as _add_keyword_links,
    keyword_data as _keyword_data,
    categories as _keyword_categories,
    keyword_row as _require_keyword,
    keywords_data as _keyword_rows_data,
    name_exists as _keyword_name_exists,
    page_keywords as _page_keywords,
    validate_links as _validate_keyword_links,
)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["关键词"],
    responses=COMMON_ERRORS,
)


@router.get("/keywords", response_model=PagedEnvelope[KeywordData])
def list_keywords(
    ctx: ProjectContext = Depends(require_permission("question.read")),
    db: Session = Depends(get_db),
    category: str | None = Query(None, max_length=64, description="按分类精确筛选"),
    is_active: bool | None = Query(None, description="按启停筛选"),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
) -> dict:
    total, rows = _page_keywords(
        db,
        ctx.project.id,
        category=category,
        is_active=is_active,
        page=page,
        page_size=page_size,
    )
    return ok_page(
        _keyword_rows_data(db, rows),
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/keywords/categories", response_model=Envelope[list[str]])
def list_keyword_categories(
    ctx: ProjectContext = Depends(require_permission("question.read")),
    db: Session = Depends(get_db),
) -> dict:
    """目标词分类字典：给前端下拉用，避免运营在输入框里精确拼分类名。"""
    return ok(_keyword_categories(db, ctx.project.id))


@router.post("/keywords", status_code=201, response_model=Envelope[KeywordData])
def create_keyword(
    payload: KeywordCreate,
    ctx: ProjectContext = Depends(require_permission("question.write")),
    db: Session = Depends(get_db),
) -> dict:
    if _keyword_name_exists(db, ctx.project.id, payload.name):
        raise ConflictError("关键词名称已存在", code="keyword_name_conflict")

    question_ids, content_version_ids = _validate_keyword_links(
        db,
        ctx.project.id,
        payload.question_ids,
        payload.content_version_ids,
    )

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
    _add_keyword_links(db, ctx.project.id, keyword.id, question_ids, content_version_ids)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="keyword.create",
        target_type="keyword",
        target_id=keyword.id,
        payload={
            "name": keyword.name,
            "category": keyword.category,
            "question_count": len(question_ids),
            "content_version_count": len(content_version_ids),
        },
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
    question_ids = changes.pop("question_ids", None)
    content_version_ids = changes.pop("content_version_ids", None)
    for field in ("name", "priority", "is_active"):
        if field in changes and changes[field] is None:
            raise AppError(f"{field} 不能为空", code="invalid_keyword_field")

    if "name" in changes and changes["name"] != keyword.name:
        if _keyword_name_exists(db, ctx.project.id, changes["name"], exclude_id=keyword.id):
            raise ConflictError("关键词名称已存在", code="keyword_name_conflict")

    for field, value in changes.items():
        setattr(keyword, field, value)

    # 关联只在显式传入时整组替换，避免「只改备注」把已有内容版本关联清空。
    linked_questions: list[uuid.UUID] | None = None
    linked_versions: list[uuid.UUID] | None = None
    if question_ids is not None or content_version_ids is not None:
        linked_questions, linked_versions = _validate_keyword_links(
            db,
            ctx.project.id,
            question_ids or [],
            content_version_ids or [],
        )
        if question_ids is not None:
            db.execute(
                delete(QuestionKeyword).where(
                    QuestionKeyword.project_id == ctx.project.id,
                    QuestionKeyword.keyword_id == keyword.id,
                )
            )
        if content_version_ids is not None:
            db.execute(
                delete(ContentVersionKeyword).where(
                    ContentVersionKeyword.project_id == ctx.project.id,
                    ContentVersionKeyword.keyword_id == keyword.id,
                )
            )
        _add_keyword_links(
            db,
            ctx.project.id,
            keyword.id,
            linked_questions if question_ids is not None else [],
            linked_versions if content_version_ids is not None else [],
        )
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
        } | (
            {} if question_ids is None else {"question_ids": [str(value) for value in linked_questions or []]}
        ) | (
            {} if content_version_ids is None else {"content_version_ids": [str(value) for value in linked_versions or []]}
        ),
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
