"""关键词接口：复用 question.read / question.write；DELETE 只做软删。

题目级关键词走 question_keywords，版本级关键词走 content_version_keywords；两者并存，按粒度使用，不互相替代。
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, select
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
from app.models import ContentVersion, ContentVersionKeyword, Keyword, Question, QuestionKeyword
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


def _keyword_payload(
    row: Keyword,
    question_ids: list[uuid.UUID],
    content_version_ids: list[uuid.UUID],
) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "category": row.category,
        "priority": row.priority,
        "is_active": row.is_active,
        "notes": row.notes,
        "question_ids": [str(value) for value in question_ids],
        "content_version_ids": [str(value) for value in content_version_ids],
        "content_version_count": len(content_version_ids),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _keyword_data(db: Session, row: Keyword) -> dict:
    question_ids = db.scalars(
        select(QuestionKeyword.question_id)
        .where(
            QuestionKeyword.project_id == row.project_id,
            QuestionKeyword.keyword_id == row.id,
        )
        .order_by(QuestionKeyword.question_id)
    ).all()
    content_version_ids = db.scalars(
        select(ContentVersionKeyword.version_id)
        .where(
            ContentVersionKeyword.project_id == row.project_id,
            ContentVersionKeyword.keyword_id == row.id,
        )
        .order_by(ContentVersionKeyword.version_id)
    ).all()
    return _keyword_payload(row, question_ids, content_version_ids)


def _keyword_rows_data(db: Session, rows: list[Keyword]) -> list[dict]:
    """列表批量取关联：两条分组查询替代每个关键词各两条，避免 N+1。"""
    if not rows:
        return []
    keyword_ids = [row.id for row in rows]
    project_id = rows[0].project_id

    question_map: dict[uuid.UUID, list[uuid.UUID]] = {}
    for keyword_id, question_id in db.execute(
        select(QuestionKeyword.keyword_id, QuestionKeyword.question_id)
        .where(
            QuestionKeyword.project_id == project_id,
            QuestionKeyword.keyword_id.in_(keyword_ids),
        )
        .order_by(QuestionKeyword.question_id)
    ).all():
        question_map.setdefault(keyword_id, []).append(question_id)

    version_map: dict[uuid.UUID, list[uuid.UUID]] = {}
    for keyword_id, version_id in db.execute(
        select(ContentVersionKeyword.keyword_id, ContentVersionKeyword.version_id)
        .where(
            ContentVersionKeyword.project_id == project_id,
            ContentVersionKeyword.keyword_id.in_(keyword_ids),
        )
        .order_by(ContentVersionKeyword.version_id)
    ).all():
        version_map.setdefault(keyword_id, []).append(version_id)

    return [
        _keyword_payload(row, question_map.get(row.id, []), version_map.get(row.id, []))
        for row in rows
    ]


def _validate_keyword_links(
    db: Session,
    project_id: uuid.UUID,
    question_ids: list[uuid.UUID],
    content_version_ids: list[uuid.UUID],
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    unique_question_ids = list(dict.fromkeys(question_ids))
    unique_version_ids = list(dict.fromkeys(content_version_ids))
    if unique_question_ids:
        found_questions = set(
            db.scalars(
                select(Question.id).where(
                    Question.project_id == project_id,
                    Question.id.in_(unique_question_ids),
                )
            ).all()
        )
        if len(found_questions) != len(unique_question_ids):
            raise AppError(
                "题目不存在或不属于当前项目",
                code="question_project_mismatch",
            )
    if unique_version_ids:
        found_versions = set(
            db.scalars(
                select(ContentVersion.id).where(
                    ContentVersion.project_id == project_id,
                    ContentVersion.id.in_(unique_version_ids),
                )
            ).all()
        )
        if len(found_versions) != len(unique_version_ids):
            raise AppError(
                "内容版本不存在或不属于当前项目",
                code="content_version_project_mismatch",
            )
    return unique_question_ids, unique_version_ids


def _add_keyword_links(
    db: Session,
    project_id: uuid.UUID,
    keyword_id: uuid.UUID,
    question_ids: list[uuid.UUID],
    content_version_ids: list[uuid.UUID],
) -> None:
    for question_id in question_ids:
        db.add(
            QuestionKeyword(
                project_id=project_id,
                question_id=question_id,
                keyword_id=keyword_id,
            )
        )
    for version_id in content_version_ids:
        db.add(
            ContentVersionKeyword(
                project_id=project_id,
                version_id=version_id,
                keyword_id=keyword_id,
            )
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
    filters = [Keyword.project_id == ctx.project.id]
    if category is not None:
        filters.append(Keyword.category == category)
    if is_active is not None:
        filters.append(Keyword.is_active == is_active)

    total = db.scalar(select(func.count()).select_from(Keyword).where(*filters)) or 0
    rows = db.scalars(
        select(Keyword)
        .where(*filters)
        .order_by(Keyword.name, Keyword.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
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
    rows = db.scalars(
        select(Keyword.category)
        .where(
            Keyword.project_id == ctx.project.id,
            Keyword.category.is_not(None),
        )
        .distinct()
        .order_by(Keyword.category)
    ).all()
    return ok([value for value in rows if value])


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
