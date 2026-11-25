"""题库接口：题目列表/新建/元信息更新与版本追加。

权限复用 question.read / question.write；正文只能新开版本，历史版本不可改。
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    Envelope,
    PagedEnvelope,
    QuestionCandidateAcceptResult,
    QuestionCandidateData,
    QuestionCandidateImportResult,
    QuestionCandidateMineResult,
    QuestionCreated,
    QuestionData,
    QuestionVersionCreated,
    QuestionVersionData,
    ok,
    ok_page,
)
from app.core.errors import ConflictError
from app.services.state_machine import ensure_question_transition
from app.db.session import get_db
from app.models import (
    Question,
    QuestionVersion,
    QuestionVersionKeyword,
)
from app.models.enums import (
    QuestionCandidateBucket,
    QuestionCandidateStatus,
    QuestionStatus,
    QuestionType,
)
from app.schemas import (
    QuestionCandidateImport,
    QuestionCandidateMine,
    QuestionCreate,
    QuestionUpdate,
    QuestionVersionCreate,
)
from app.services import question_mining
from app.services.question_listing import (
    code_exists as _question_code_exists,
    current_text as _current_text,
    max_version_no as _max_version_no,
    page_questions as _page_questions,
    page_versions as _page_versions,
    question_row as _require_question,
    version_keyword_rows as _version_keyword_rows,
)
from app.services.audit import record_audit

router = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["题库"],
    responses=COMMON_ERRORS,
)

def _question_data(db: Session, row: Question) -> dict:
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
        "current_text": _current_text(db, row),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _version_data(row: QuestionVersion) -> dict:
    return {
        "id": str(row.id),
        "question_id": str(row.question_id),
        "version_no": row.version_no,
        "text": row.text,
        "question_type": (
            row.question_type.value if row.question_type is not None else None
        ),
        "audience": row.audience,
        "intent": row.intent,
        "priority": row.priority,
        "change_note": row.change_note,
        "created_by": str(row.created_by) if row.created_by else None,
        "created_at": row.created_at,
    }


def _apply_version_snapshot(question: Question, version: QuestionVersion) -> None:
    """新版本快照当前问题的测量语义，之后 Question 再改也不影响历史版本。"""
    version.question_type = question.question_type
    version.audience = question.audience
    version.intent = question.intent
    version.priority = question.priority


def _snapshot_version_keywords(
    db: Session,
    *,
    project_id: uuid.UUID,
    question: Question,
    version: QuestionVersion,
) -> None:
    """把题目当前关键词复制到版本；失败不静默忽略，由唯一约束兜底重复。"""
    for row in _version_keyword_rows(db, project_id, question.id):
        db.add(
            QuestionVersionKeyword(
                project_id=project_id,
                question_version_id=version.id,
                keyword_id=row.keyword_id,
            )
        )

@router.get(
    "/question-candidates",
    response_model=PagedEnvelope[QuestionCandidateData],
)
def list_question_candidates(
    ctx: ProjectContext = Depends(require_permission("question.read")),
    db: Session = Depends(get_db),
    status: QuestionCandidateStatus | None = Query(None, description="候选状态"),
    bucket: QuestionCandidateBucket | None = Query(None, description="category / purchase / reputation"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    rows, total = question_mining.list_candidates(
        db,
        project_id=ctx.project.id,
        status=status,
        bucket=bucket,
        page=page,
        page_size=page_size,
    )
    return ok_page(
        [question_mining.candidate_payload(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post(
    "/question-candidates/mine",
    response_model=Envelope[QuestionCandidateMineResult],
)
def mine_question_candidates(
    payload: QuestionCandidateMine,
    ctx: ProjectContext = Depends(require_permission("question.write")),
    db: Session = Depends(get_db),
) -> dict:
    result = question_mining.mine_candidates(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        limit=payload.limit,
        buckets=payload.buckets or None,
    )
    db.commit()
    return ok(
        {
            "created_count": result["created_count"],
            "skipped_count": result["skipped_count"],
            "counts": result["counts"],
            "missing_context": result["missing_context"],
        }
    )


@router.post(
    "/question-candidates/import",
    response_model=Envelope[QuestionCandidateImportResult],
)
def import_question_candidates(
    payload: QuestionCandidateImport,
    ctx: ProjectContext = Depends(require_permission("question.write")),
    db: Session = Depends(get_db),
) -> dict:
    result = question_mining.import_candidates(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        texts=payload.texts,
        bucket=payload.bucket,
        source_ref=payload.source_ref,
    )
    db.commit()
    return ok(
        {
            "created_count": result["created_count"],
            "skipped_count": result["skipped_count"],
            "counts": result["counts"],
        }
    )


@router.post(
    "/question-candidates/{candidate_id}/accept",
    response_model=Envelope[QuestionCandidateAcceptResult],
)
def accept_question_candidate(
    candidate_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("question.write")),
    db: Session = Depends(get_db),
) -> dict:
    result = question_mining.accept_candidate(
        db,
        project_id=ctx.project.id,
        candidate_id=candidate_id,
        actor_id=ctx.user.id,
    )
    db.commit()
    return ok(
        {
            "candidate_id": str(result["candidate_id"]),
            "question_id": str(result["question_id"]),
            "question_code": result["question_code"],
            "version_no": result["version_no"],
        }
    )


@router.post(
    "/question-candidates/{candidate_id}/reject",
    response_model=Envelope[QuestionCandidateData],
)
def reject_question_candidate(
    candidate_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("question.write")),
    db: Session = Depends(get_db),
) -> dict:
    row = question_mining.reject_candidate(
        db,
        project_id=ctx.project.id,
        candidate_id=candidate_id,
        actor_id=ctx.user.id,
    )
    db.commit()
    return ok(question_mining.candidate_payload(row))


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
    rows, total = _page_questions(db, filters, page=page, page_size=page_size)
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
    if _question_code_exists(db, ctx.project.id, payload.code):
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
    _apply_version_snapshot(question, version)
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
        question.status = ensure_question_transition(question.status, new_status)

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
    rows, total = _page_versions(db, filters, page=page, page_size=page_size)
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
    next_no = _max_version_no(db, ctx.project.id, question.id) + 1
    version = QuestionVersion(
        project_id=ctx.project.id,
        question_id=question.id,
        version_no=next_no,
        text=payload.text,
        change_note=payload.change_note,
        created_by=ctx.user.id,
    )
    _apply_version_snapshot(question, version)
    db.add(version)
    db.flush()
    _snapshot_version_keywords(
        db, project_id=ctx.project.id, question=question, version=version
    )
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
