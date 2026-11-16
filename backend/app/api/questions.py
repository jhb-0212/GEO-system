"""题库接口：题目列表/新建/元信息更新与版本追加。

权限复用 question.read / question.write；正文只能新开版本，历史版本不可改。
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
    PagedEnvelope,
    QuestionCreated,
    QuestionData,
    QuestionVersionCreated,
    QuestionVersionData,
    ok,
    ok_page,
)
from app.core.errors import ConflictError, ResourceMissingError
from app.db.session import get_db
from app.models import Question, QuestionVersion
from app.models.enums import QuestionStatus, QuestionType
from app.schemas import QuestionCreate, QuestionUpdate, QuestionVersionCreate
from app.services.audit import record_audit

router = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["题库"],
    responses=COMMON_ERRORS,
)

_ALLOWED_TRANSITIONS: dict[QuestionStatus, set[QuestionStatus]] = {
    QuestionStatus.DRAFT: {QuestionStatus.ACTIVE},
    QuestionStatus.ACTIVE: {QuestionStatus.ARCHIVED},
    QuestionStatus.ARCHIVED: {QuestionStatus.ACTIVE},
}


def _require_question(
    db: Session,
    project_id: uuid.UUID,
    question_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> Question:
    query = select(Question).where(
        Question.id == question_id,
        Question.project_id == project_id,
    )
    if for_update:
        query = query.with_for_update()
    row = db.scalar(query)
    if row is None:
        raise ResourceMissingError("题目不存在或不属于当前项目", code="question_missing")
    return row


def _question_data(db: Session, row: Question) -> dict:
    current_text = db.scalar(
        select(QuestionVersion.text).where(
            QuestionVersion.project_id == row.project_id,
            QuestionVersion.question_id == row.id,
            QuestionVersion.version_no == row.current_version_no,
        )
    )
    return {
        "id": str(row.id),
        "code": row.code,
        "title": row.title,
        "question_type": row.question_type.value,
        "audience": row.audience,
        "intent": row.intent,
        "priority": row.priority,
        "status": row.status.value,
        "current_version_no": row.current_version_no,
        "current_text": current_text,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _version_data(row: QuestionVersion) -> dict:
    return {
        "id": str(row.id),
        "question_id": str(row.question_id),
        "version_no": row.version_no,
        "text": row.text,
        "change_note": row.change_note,
        "created_by": str(row.created_by) if row.created_by else None,
        "created_at": row.created_at,
    }


def _ensure_status_transition(current: QuestionStatus, new: QuestionStatus) -> None:
    if new == current:
        return
    if new not in _ALLOWED_TRANSITIONS[current]:
        raise ConflictError(
            f"题目状态不允许从 {current.value} 变为 {new.value}",
            code="question_status_conflict",
        )


@router.get("/questions", response_model=PagedEnvelope[QuestionData])
def list_questions(
    ctx: ProjectContext = Depends(require_permission("question.read")),
    db: Session = Depends(get_db),
    status: QuestionStatus | None = Query(None, description="按题目状态筛选"),
    question_type: QuestionType | None = Query(None, description="brand / general"),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
) -> dict:
    filters = [Question.project_id == ctx.project.id]
    if status is not None:
        filters.append(Question.status == status)
    if question_type is not None:
        filters.append(Question.question_type == question_type)
    total = db.scalar(select(func.count()).select_from(Question).where(*filters)) or 0
    rows = db.scalars(
        select(Question)
        .where(*filters)
        .order_by(Question.code, Question.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page(
        [_question_data(db, row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/questions", status_code=201, response_model=Envelope[QuestionCreated])
def create_question(
    payload: QuestionCreate,
    ctx: ProjectContext = Depends(require_permission("question.write")),
    db: Session = Depends(get_db),
) -> dict:
    existing = db.scalar(
        select(Question.id).where(
            Question.project_id == ctx.project.id,
            Question.code == payload.code,
        )
    )
    if existing is not None:
        raise ConflictError("题目 code 已存在", code="question_code_conflict")

    question = Question(
        project_id=ctx.project.id,
        code=payload.code,
        title=payload.title,
        question_type=payload.question_type,
        audience=payload.audience,
        intent=payload.intent,
        priority=payload.priority,
        status=payload.status,
        current_version_no=1,
    )
    db.add(question)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("题目 code 已存在", code="question_code_conflict") from exc

    version = QuestionVersion(
        project_id=ctx.project.id,
        question_id=question.id,
        version_no=1,
        text=payload.text,
        created_by=ctx.user.id,
    )
    db.add(version)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="question.create",
        target_type="question",
        target_id=question.id,
        payload={
            "code": question.code,
            "question_type": question.question_type.value,
            "status": question.status.value,
            "version_no": 1,
        },
    )
    db.commit()
    return ok({"id": str(question.id), "version_no": 1})


@router.patch("/questions/{question_id}", response_model=Envelope[QuestionData])
def update_question(
    question_id: uuid.UUID,
    payload: QuestionUpdate,
    ctx: ProjectContext = Depends(require_permission("question.write")),
    db: Session = Depends(get_db),
) -> dict:
    question = _require_question(db, ctx.project.id, question_id, for_update=True)
    changes = payload.model_dump(exclude_unset=True)
    new_status = changes.pop("status", None)
    if new_status is not None:
        _ensure_status_transition(question.status, new_status)
        question.status = new_status

    for field in ("audience", "intent", "priority"):
        if field in changes:
            setattr(question, field, changes[field])

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="question.update",
        target_type="question",
        target_id=question.id,
        payload={
            key: (value.value if hasattr(value, "value") else value)
            for key, value in changes.items()
        }
        | ({"status": new_status.value} if new_status is not None else {}),
    )
    db.commit()
    return ok(_question_data(db, question))


@router.get(
    "/questions/{question_id}/versions",
    response_model=PagedEnvelope[QuestionVersionData],
)
def list_question_versions(
    question_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("question.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
) -> dict:
    _require_question(db, ctx.project.id, question_id)
    filters = [
        QuestionVersion.project_id == ctx.project.id,
        QuestionVersion.question_id == question_id,
    ]
    total = (
        db.scalar(select(func.count()).select_from(QuestionVersion).where(*filters)) or 0
    )
    rows = db.scalars(
        select(QuestionVersion)
        .where(*filters)
        .order_by(QuestionVersion.version_no)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page(
        [_version_data(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post(
    "/questions/{question_id}/versions",
    status_code=201,
    response_model=Envelope[QuestionVersionCreated],
)
def create_question_version(
    question_id: uuid.UUID,
    payload: QuestionVersionCreate,
    ctx: ProjectContext = Depends(require_permission("question.write")),
    db: Session = Depends(get_db),
) -> dict:
    question = _require_question(db, ctx.project.id, question_id, for_update=True)
    current_max = db.scalar(
        select(func.max(QuestionVersion.version_no)).where(
            QuestionVersion.project_id == ctx.project.id,
            QuestionVersion.question_id == question.id,
        )
    )
    next_no = (current_max or 0) + 1
    version = QuestionVersion(
        project_id=ctx.project.id,
        question_id=question.id,
        version_no=next_no,
        text=payload.text,
        change_note=payload.change_note,
        created_by=ctx.user.id,
    )
    db.add(version)
    db.flush()
    question.current_version_no = next_no
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="question.version_add",
        target_type="question_version",
        target_id=version.id,
        payload={"question_id": str(question.id), "version_no": next_no},
    )
    db.commit()
    return ok({"version_id": str(version.id), "version_no": next_no})
