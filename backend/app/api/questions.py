"""项目题库与目标词：正文只追加版本，跨项目关联一律拒绝。"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS, Envelope, KeywordData, PagedEnvelope, QuestionData,
    QuestionVersionData, ok, ok_page,
)
from app.core.errors import AppError
from app.db.session import get_db
from app.models import ContentVersion, ContentVersionKeyword, Keyword, Question, QuestionKeyword, QuestionVersion
from app.models.enums import QuestionStatus
from app.schemas import KeywordCreate, QuestionCreate, QuestionUpdate, QuestionVersionCreate
from app.services.audit import record_audit
from app.services.project_scope import require_scoped_row

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["题库与目标词"], responses=COMMON_ERRORS)


def _version_data(row: QuestionVersion) -> dict:
    return {
        "id": str(row.id), "question_id": str(row.question_id), "version_no": row.version_no,
        "text": row.text, "change_note": row.change_note, "created_at": row.created_at,
    }


def _question_data(db: Session, row: Question) -> dict:
    version = db.scalar(select(QuestionVersion).where(
        QuestionVersion.project_id == row.project_id,
        QuestionVersion.question_id == row.id,
        QuestionVersion.version_no == row.current_version_no,
    ))
    return {
        "id": str(row.id), "code": row.code, "title": row.title,
        "question_type": row.question_type.value, "audience": row.audience,
        "intent": row.intent, "priority": row.priority, "status": row.status.value,
        "current_version_no": row.current_version_no,
        "current_text": version.text if version else None,
    }


@router.get("/questions", response_model=PagedEnvelope[QuestionData])
def list_questions(
    ctx: ProjectContext = Depends(require_permission("question.read")),
    db: Session = Depends(get_db),
    status: QuestionStatus | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    filters = [Question.project_id == ctx.project.id]
    if status is not None:
        filters.append(Question.status == status)
    total = db.scalar(select(func.count()).select_from(Question).where(*filters)) or 0
    rows = db.scalars(select(Question).where(*filters).order_by(Question.code)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return ok_page([_question_data(db, row) for row in rows], page=page, page_size=page_size, total=total)


@router.post("/questions", status_code=201, response_model=Envelope[QuestionData])
def create_question(
    payload: QuestionCreate,
    ctx: ProjectContext = Depends(require_permission("question.write")),
    db: Session = Depends(get_db),
) -> dict:
    if db.scalar(select(Question.id).where(Question.project_id == ctx.project.id, Question.code == payload.code)):
        raise AppError("题目 code 已存在", code="question_code_conflict")
    row = Question(project_id=ctx.project.id, code=payload.code, title=payload.title,
                   question_type=payload.question_type, audience=payload.audience, intent=payload.intent,
                   priority=payload.priority, status=payload.status, current_version_no=1)
    db.add(row)
    try:
        db.flush()
        db.add(QuestionVersion(project_id=ctx.project.id, question_id=row.id, version_no=1,
                               text=payload.initial_text, created_by=ctx.user.id))
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise AppError("题目 code 已存在", code="question_code_conflict") from exc
    record_audit(db, project_id=ctx.project.id, actor_id=ctx.user.id, action="question.create",
                 target_type="question", target_id=row.id, payload={"code": row.code, "status": row.status.value})
    db.commit()
    return ok(_question_data(db, row))


@router.patch("/questions/{question_id}", response_model=Envelope[QuestionData])
def update_question(
    question_id: uuid.UUID, payload: QuestionUpdate,
    ctx: ProjectContext = Depends(require_permission("question.write")),
    db: Session = Depends(get_db),
) -> dict:
    row = require_scoped_row(db, Question, ctx.project.id, resource="question", for_update=True, id=question_id)
    changes = payload.model_dump(exclude_unset=True)
    if any(changes.get(field) is None for field in ("status", "priority") if field in changes):
        raise AppError("状态和优先级不能清空", code="invalid_question_field")
    if changes.get("status") == QuestionStatus.ACTIVE:
        version = db.scalar(select(QuestionVersion.id).where(
            QuestionVersion.project_id == ctx.project.id, QuestionVersion.question_id == row.id,
            QuestionVersion.version_no == row.current_version_no,
        ))
        if version is None:
            raise AppError("当前问法版本不存在", code="question_version_missing")
    for field, value in changes.items():
        setattr(row, field, value)
    record_audit(db, project_id=ctx.project.id, actor_id=ctx.user.id, action="question.update",
                 target_type="question", target_id=row.id, payload={key: str(value) if value is not None else None for key, value in changes.items()})
    db.commit()
    return ok(_question_data(db, row))


@router.get("/questions/{question_id}/versions", response_model=PagedEnvelope[QuestionVersionData])
def list_versions(
    question_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("question.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
) -> dict:
    require_scoped_row(db, Question, ctx.project.id, resource="question", id=question_id)
    filters = [QuestionVersion.project_id == ctx.project.id, QuestionVersion.question_id == question_id]
    total = db.scalar(select(func.count()).select_from(QuestionVersion).where(*filters)) or 0
    rows = db.scalars(select(QuestionVersion).where(*filters).order_by(QuestionVersion.version_no.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return ok_page([_version_data(row) for row in rows], page=page, page_size=page_size, total=total)


@router.post("/questions/{question_id}/versions", status_code=201, response_model=Envelope[QuestionVersionData])
def create_version(
    question_id: uuid.UUID, payload: QuestionVersionCreate,
    ctx: ProjectContext = Depends(require_permission("question.write")),
    db: Session = Depends(get_db),
) -> dict:
    row = require_scoped_row(db, Question, ctx.project.id, resource="question", for_update=True, id=question_id)
    max_version = db.scalar(select(func.max(QuestionVersion.version_no)).where(
        QuestionVersion.project_id == ctx.project.id, QuestionVersion.question_id == row.id,
    )) or 0
    version = QuestionVersion(project_id=ctx.project.id, question_id=row.id, version_no=max_version + 1,
                              text=payload.text, change_note=payload.change_note, created_by=ctx.user.id)
    db.add(version)
    row.current_version_no = version.version_no
    db.flush()
    record_audit(db, project_id=ctx.project.id, actor_id=ctx.user.id, action="question.version.create",
                 target_type="question_version", target_id=version.id,
                 payload={"question_id": str(row.id), "version_no": version.version_no})
    db.commit()
    return ok(_version_data(version))


def _keyword_data(db: Session, row: Keyword) -> dict:
    question_ids = db.scalars(select(QuestionKeyword.question_id).where(
        QuestionKeyword.project_id == row.project_id, QuestionKeyword.keyword_id == row.id)).all()
    version_ids = db.scalars(select(ContentVersionKeyword.version_id).where(
        ContentVersionKeyword.project_id == row.project_id, ContentVersionKeyword.keyword_id == row.id)).all()
    return {"id": str(row.id), "name": row.name, "category": row.category,
            "priority": row.priority, "is_active": row.is_active, "notes": row.notes,
            "question_ids": sorted(str(value) for value in question_ids),
            "content_version_ids": sorted(str(value) for value in version_ids)}


@router.get("/keywords", response_model=PagedEnvelope[KeywordData])
def list_keywords(
    ctx: ProjectContext = Depends(require_permission("question.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
) -> dict:
    filters = [Keyword.project_id == ctx.project.id]
    total = db.scalar(select(func.count()).select_from(Keyword).where(*filters)) or 0
    rows = db.scalars(select(Keyword).where(*filters).order_by(Keyword.priority, Keyword.name)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return ok_page([_keyword_data(db, row) for row in rows], page=page, page_size=page_size, total=total)


@router.post("/keywords", status_code=201, response_model=Envelope[KeywordData])
def create_keyword(
    payload: KeywordCreate,
    ctx: ProjectContext = Depends(require_permission("question.write")),
    db: Session = Depends(get_db),
) -> dict:
    name = payload.name.strip()
    if not name:
        raise AppError("目标词不能为空", code="invalid_keyword_name")
    if db.scalar(select(Keyword.id).where(Keyword.project_id == ctx.project.id, Keyword.name == name)):
        raise AppError("目标词已存在", code="keyword_name_conflict")
    question_ids = set(payload.question_ids)
    version_ids = set(payload.content_version_ids)
    if question_ids:
        found = set(db.scalars(select(Question.id).where(
            Question.project_id == ctx.project.id, Question.id.in_(question_ids))).all())
        if found != question_ids:
            raise AppError("题目不属于当前项目", code="question_project_mismatch")
    if version_ids:
        found = set(db.scalars(select(ContentVersion.id).where(
            ContentVersion.project_id == ctx.project.id, ContentVersion.id.in_(version_ids))).all())
        if found != version_ids:
            raise AppError("内容版本不属于当前项目", code="content_project_mismatch")
    row = Keyword(project_id=ctx.project.id, name=name, category=payload.category,
                  priority=payload.priority, is_active=payload.is_active, notes=payload.notes)
    db.add(row)
    try:
        db.flush()
        db.add_all(QuestionKeyword(project_id=ctx.project.id, question_id=question_id, keyword_id=row.id)
                   for question_id in question_ids)
        db.add_all(ContentVersionKeyword(project_id=ctx.project.id, version_id=version_id, keyword_id=row.id)
                   for version_id in version_ids)
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise AppError("目标词已存在", code="keyword_name_conflict") from exc
    record_audit(db, project_id=ctx.project.id, actor_id=ctx.user.id, action="keyword.create",
                 target_type="keyword", target_id=row.id,
                 payload={"question_count": len(question_ids), "content_version_count": len(version_ids)})
    db.commit()
    return ok(_keyword_data(db, row))
