"""权威事实库与回答事实核验接口。

权限沿用内容审批：content.write 录入与修订，content.review 审批；
回答事实核验使用 evidence.review，错误/过期自动生成纠错任务。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    CorrectionTaskData,
    Envelope,
    FactClaimData,
    FactData,
    FactVersionData,
    PagedEnvelope,
    ok,
    ok_page,
)
from app.core.errors import ConflictError, ResourceMissingError
from app.services.state_machine import (
    ensure_correction_task_transition,
    ensure_fact_transition,
)
from app.db.session import get_db
from app.models import (
    AnswerFactClaim,
    CorrectionTask,
    Fact,
    FactVersion,
    MonitoringCitation,
    MonitoringSample,
)
from pydantic import BaseModel, Field

from app.models.enums import (
    CorrectionTaskStatus,
    FactClaimVerdict,
    FactStatus,
    FactType,
    FactVersionAction,
    PushStatus,
    PushTargetType,
    ReviewDecision,
)
from app.schemas import (
    CorrectionTaskUpdate,
    FactClaimCreate,
    FactClaimReviewRequest,
    FactCreate,
    FactReviewRequest,
    FactUpdate,
)
from app.services.audit import record_audit
from app.services import fact_push
from app.services.fact_listing import (
    fact_row as _require_fact,
    page_claims as _page_claims,
    page_corrections as _page_corrections,
    page_facts as _page_facts,
    page_versions as _page_versions,
)
from app.services.fact_library import append_fact_version, ensure_approvable, fact_snapshot
from app.services.industry_presets import project_industry_config
from app.services.project_scope import require_scoped_row

router = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["事实库"],
    responses=COMMON_ERRORS,
)

FACT_TYPE_ORDER = list(FactType)


def _fact_data(fact: Fact) -> dict:
    return {
        "id": str(fact.id),
        "fact_type": fact.fact_type.value,
        "fact_key": fact.fact_key,
        "fact_value": fact.fact_value,
        "source_document": fact.source_document,
        "source_url": fact.source_url,
        "owner": fact.owner,
        "approval_status": fact.approval_status.value,
        "effective_from": fact.effective_from,
        "effective_until": fact.effective_until,
        "version_no": fact.version_no,
        "superseded_by": str(fact.superseded_by) if fact.superseded_by else None,
        "business_confirmed": fact.business_confirmed,
        "business_confirmed_note": fact.business_confirmed_note,
        "created_by": str(fact.created_by) if fact.created_by else None,
        "approved_by": str(fact.approved_by) if fact.approved_by else None,
        "approved_at": fact.approved_at,
        "rejection_note": fact.rejection_note,
        "created_at": fact.created_at,
        "updated_at": fact.updated_at,
    }


def _claim_data(claim: AnswerFactClaim) -> dict:
    return {
        "id": str(claim.id),
        "serial_no": claim.serial_no,
        "sample_id": str(claim.sample_id),
        "citation_id": str(claim.citation_id) if claim.citation_id else None,
        "claim_text": claim.claim_text,
        "fact_id": str(claim.fact_id) if claim.fact_id else None,
        "verdict": claim.verdict.value if claim.verdict else None,
        "source_url": claim.source_url,
        "reviewed_by": str(claim.reviewed_by) if claim.reviewed_by else None,
        "reviewed_at": claim.reviewed_at,
        "correction_task_id": str(claim.correction_task_id) if claim.correction_task_id else None,
        "created_at": claim.created_at,
    }


def _correction_data(task: CorrectionTask) -> dict:
    return {
        "id": str(task.id),
        "claim_id": str(task.claim_id) if task.claim_id else None,
        "fact_id": str(task.fact_id) if task.fact_id else None,
        "title": task.title,
        "description": task.description,
        "source_url": task.source_url,
        "status": task.status.value,
        "priority": task.priority,
        "created_by": str(task.created_by) if task.created_by else None,
        "resolved_at": task.resolved_at,
        "created_at": task.created_at,
    }


@router.get("/facts/types", response_model=Envelope[list[dict]])
def list_fact_types(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
) -> dict:
    label_map = project_industry_config(db, ctx.project.id)["labels"]["fact_types"]
    labels: dict[FactType, str] = {
        item: label_map.get(item.value, item.value) for item in FACT_TYPE_ORDER
    }
    return ok([{"value": item.value, "label": labels[item]} for item in FACT_TYPE_ORDER])


@router.get("/facts", response_model=PagedEnvelope[FactData])
def list_facts(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    fact_type: FactType | None = Query(None),
    approval_status: FactStatus | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> dict:
    filters = [Fact.project_id == ctx.project.id]
    if fact_type is not None:
        filters.append(Fact.fact_type == fact_type)
    if approval_status is not None:
        filters.append(Fact.approval_status == approval_status)
    rows, total = _page_facts(db, filters, page=page, page_size=page_size)
    return ok_page([_fact_data(row) for row in rows], page=page, page_size=page_size, total=total)


@router.post("/facts", status_code=201, response_model=Envelope[FactData])
def create_fact(
    payload: FactCreate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    fact = Fact(
        project_id=ctx.project.id,
        fact_type=payload.fact_type,
        fact_key=payload.fact_key.strip(),
        fact_value=payload.fact_value.strip(),
        source_document=payload.source_document,
        source_url=payload.source_url,
        owner=payload.owner,
        effective_from=payload.effective_from,
        effective_until=payload.effective_until,
        business_confirmed=payload.business_confirmed,
        business_confirmed_note=payload.business_confirmed_note,
        version_no=1,
        created_by=ctx.user.id,
    )
    db.add(fact)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise ConflictError("同一事实类型下该标识已存在", code="fact_duplicate") from error
    append_fact_version(
        db,
        fact,
        action=FactVersionAction.CREATED,
        actor_id=ctx.user.id,
        change_note=payload.change_note,
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="fact.create",
        target_type="fact",
        target_id=fact.id,
        payload={"fact_type": fact.fact_type.value, "fact_key": fact.fact_key},
    )
    db.commit()
    return ok(_fact_data(fact))


@router.get("/facts/{fact_id}", response_model=Envelope[FactData])
def get_fact(
    fact_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
) -> dict:
    return ok(_fact_data(_require_fact(db, ctx.project.id, fact_id)))


@router.patch("/facts/{fact_id}", response_model=Envelope[FactData])
def update_fact(
    fact_id: uuid.UUID,
    payload: FactUpdate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    fact = _require_fact(db, ctx.project.id, fact_id, for_update=True)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise ConflictError("没有需要更新的事实字段", code="fact_no_changes")
    previous = fact_snapshot(fact)
    for key, value in changes.items():
        if key == "change_note":
            continue
        setattr(fact, key, value.strip() if isinstance(value, str) else value)
    fact.version_no += 1
    # 已批准或待审的事实被修改后回到草稿，审批人需要重新确认新内容
    if fact.approval_status in (FactStatus.APPROVED, FactStatus.PENDING_REVIEW):
        fact.approval_status = ensure_fact_transition(fact.approval_status, FactStatus.DRAFT)
        fact.approved_by = None
        fact.approved_at = None
    fact.rejection_note = None
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise ConflictError("同一事实类型下该标识已存在", code="fact_duplicate") from error
    append_fact_version(
        db,
        fact,
        action=FactVersionAction.REVISED,
        actor_id=ctx.user.id,
        previous_snapshot=previous,
        change_note=changes.get("change_note"),
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="fact.update",
        target_type="fact",
        target_id=fact.id,
        payload={"version_no": fact.version_no},
    )
    db.commit()
    return ok(_fact_data(fact))


@router.post("/facts/{fact_id}/submit", response_model=Envelope[FactData])
def submit_fact(
    fact_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    fact = _require_fact(db, ctx.project.id, fact_id, for_update=True)
    if fact.approval_status != FactStatus.DRAFT:
        raise ConflictError("只有草稿事实能提交审批", code="fact_review_state")
    previous = fact_snapshot(fact)
    fact.approval_status = ensure_fact_transition(
        fact.approval_status, FactStatus.PENDING_REVIEW
    )
    append_fact_version(
        db,
        fact,
        action=FactVersionAction.SUBMITTED,
        actor_id=ctx.user.id,
        previous_snapshot=previous,
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="fact.submit",
        target_type="fact",
        target_id=fact.id,
        payload={"version_no": fact.version_no},
    )
    db.commit()
    return ok(_fact_data(fact))


@router.post("/facts/{fact_id}/review", response_model=Envelope[FactData])
def review_fact(
    fact_id: uuid.UUID,
    payload: FactReviewRequest,
    ctx: ProjectContext = Depends(require_permission("content.review")),
    db: Session = Depends(get_db),
) -> dict:
    fact = _require_fact(db, ctx.project.id, fact_id, for_update=True)
    if fact.created_by is not None and fact.created_by == ctx.user.id:
        raise ConflictError("不能审批自己录入的事实", code="review_self_not_allowed")
    previous = fact_snapshot(fact)
    industry = project_industry_config(db, ctx.project.id)
    if payload.decision == ReviewDecision.APPROVED:
        fact.business_confirmed = payload.business_confirmed
        fact.business_confirmed_note = payload.business_confirmed_note
        ensure_approvable(
            fact,
            business_confirmed=payload.business_confirmed,
            guarantee_terms=tuple(industry["quality"]["guarantee_terms"]),
            guarantee_message=industry["quality"].get("guarantee_message"),
        )
        fact.approval_status = ensure_fact_transition(
            fact.approval_status, FactStatus.APPROVED
        )
        fact.approved_by = ctx.user.id
        fact.approved_at = datetime.now(timezone.utc)
        fact.rejection_note = None
        action = FactVersionAction.APPROVED
    else:
        if fact.approval_status != FactStatus.PENDING_REVIEW:
            raise ConflictError("事实尚未提交审批或已处理", code="fact_review_state")
        fact.approval_status = ensure_fact_transition(fact.approval_status, FactStatus.DRAFT)
        fact.rejection_note = payload.comment
        action = FactVersionAction.REJECTED
    append_fact_version(
        db,
        fact,
        action=action,
        actor_id=ctx.user.id,
        previous_snapshot=previous,
        change_note=payload.comment,
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action=f"fact.{action.value}",
        target_type="fact",
        target_id=fact.id,
        payload={"version_no": fact.version_no, "decision": payload.decision.value},
    )
    db.commit()
    return ok(_fact_data(fact))


@router.post("/facts/{fact_id}/expire", response_model=Envelope[FactData])
def expire_fact(
    fact_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.review")),
    db: Session = Depends(get_db),
) -> dict:
    fact = _require_fact(db, ctx.project.id, fact_id, for_update=True)
    if fact.approval_status != FactStatus.APPROVED:
        raise ConflictError("只有已批准事实能标记过期", code="fact_review_state")
    previous = fact_snapshot(fact)
    fact.approval_status = ensure_fact_transition(fact.approval_status, FactStatus.EXPIRED)
    append_fact_version(
        db,
        fact,
        action=FactVersionAction.EXPIRED,
        actor_id=ctx.user.id,
        previous_snapshot=previous,
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="fact.expire",
        target_type="fact",
        target_id=fact.id,
        payload={"version_no": fact.version_no},
    )
    db.commit()
    return ok(_fact_data(fact))


@router.get("/facts/{fact_id}/versions", response_model=PagedEnvelope[FactVersionData])
def list_fact_versions(
    fact_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    _require_fact(db, ctx.project.id, fact_id)
    filters = [FactVersion.project_id == ctx.project.id, FactVersion.fact_id == fact_id]
    rows, total = _page_versions(db, filters, page=page, page_size=page_size)
    return ok_page(
        [
            {
                "version_no": row.version_no,
                "action": row.action.value,
                "snapshot": row.snapshot,
                "previous_snapshot": row.previous_snapshot,
                "change_note": row.change_note,
                "actor_id": str(row.actor_id) if row.actor_id else None,
                "created_at": row.created_at,
            }
            for row in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/fact-claims", response_model=PagedEnvelope[FactClaimData])
def list_fact_claims(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    sample_id: uuid.UUID | None = Query(None),
    verdict: FactClaimVerdict | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    filters = [AnswerFactClaim.project_id == ctx.project.id]
    if sample_id is not None:
        filters.append(AnswerFactClaim.sample_id == sample_id)
    if verdict is not None:
        filters.append(AnswerFactClaim.verdict == verdict)
    rows, total = _page_claims(db, filters, page=page, page_size=page_size)
    return ok_page(
        [_claim_data(row) for row in rows], page=page, page_size=page_size, total=total
    )


@router.post(
    "/monitoring/samples/{sample_id}/fact-claims",
    status_code=201,
    response_model=Envelope[FactClaimData],
)
def create_fact_claim(
    sample_id: uuid.UUID,
    payload: FactClaimCreate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    sample = require_scoped_row(
        db, MonitoringSample, ctx.project.id, resource="sample", id=sample_id
    )
    fact = None
    if payload.fact_id is not None:
        fact = _require_fact(db, ctx.project.id, payload.fact_id)
        if fact.approval_status != FactStatus.APPROVED:
            raise ConflictError("只能关联已批准事实", code="fact_not_approved")
    citation_id = payload.citation_id
    source_url = payload.source_url
    if citation_id is not None:
        citation = require_scoped_row(
            db, MonitoringCitation, ctx.project.id, resource="citation", id=citation_id
        )
        if citation.sample_id != sample.id:
            raise ConflictError("引用不属于该样本", code="citation_sample_mismatch")
        source_url = source_url or citation.raw_url
    claim = AnswerFactClaim(
        project_id=ctx.project.id,
        sample_id=sample.id,
        citation_id=citation_id,
        claim_text=payload.claim_text.strip(),
        fact_id=fact.id if fact else None,
        source_url=source_url,
        created_by=ctx.user.id,
    )
    db.add(claim)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="fact_claim.create",
        target_type="answer_fact_claim",
        target_id=claim.id,
        payload={"sample_id": str(sample.id), "fact_id": str(fact.id) if fact else None},
    )
    db.commit()
    return ok(_claim_data(claim))


@router.patch(
    "/fact-claims/{claim_id}",
    response_model=Envelope[FactClaimData],
)
def review_fact_claim(
    claim_id: uuid.UUID,
    payload: FactClaimReviewRequest,
    ctx: ProjectContext = Depends(require_permission("evidence.review")),
    db: Session = Depends(get_db),
) -> dict:
    claim = require_scoped_row(
        db, AnswerFactClaim, ctx.project.id, resource="fact_claim", for_update=True, id=claim_id
    )
    claim.verdict = payload.verdict
    claim.reviewed_by = ctx.user.id
    claim.reviewed_at = datetime.now(timezone.utc)
    if payload.verdict in (FactClaimVerdict.WRONG, FactClaimVerdict.EXPIRED):
        if payload.create_correction_task and claim.correction_task_id is None:
            task = CorrectionTask(
                project_id=ctx.project.id,
                claim_id=claim.id,
                fact_id=claim.fact_id,
                title=f"事实纠错：{claim.claim_text[:120]}",
                description=payload.review_note,
                source_url=claim.source_url,
                status=CorrectionTaskStatus.OPEN,
                priority=2,
                created_by=ctx.user.id,
            )
            db.add(task)
            db.flush()
            claim.correction_task_id = task.id
    elif claim.correction_task_id is not None:
        # 复核改判为正确/无法确认时，把此前自动生成的纠错任务关掉，避免误派活
        task = db.get(CorrectionTask, claim.correction_task_id)
        if task is not None and task.status == CorrectionTaskStatus.OPEN:
            task.status = ensure_correction_task_transition(
                task.status, CorrectionTaskStatus.DISMISSED
            )
            task.resolved_at = datetime.now(timezone.utc)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="fact_claim.review",
        target_type="answer_fact_claim",
        target_id=claim.id,
        payload={"verdict": payload.verdict.value},
    )
    db.commit()
    return ok(_claim_data(claim))


@router.get("/correction-tasks", response_model=PagedEnvelope[CorrectionTaskData])
def list_correction_tasks(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    status: CorrectionTaskStatus | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    filters = [CorrectionTask.project_id == ctx.project.id]
    if status is not None:
        filters.append(CorrectionTask.status == status)
    rows, total = _page_corrections(db, filters, page=page, page_size=page_size)
    return ok_page(
        [_correction_data(row) for row in rows], page=page, page_size=page_size, total=total
    )


@router.patch("/correction-tasks/{task_id}", response_model=Envelope[CorrectionTaskData])
def update_correction_task(
    task_id: uuid.UUID,
    payload: CorrectionTaskUpdate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    task = require_scoped_row(
        db, CorrectionTask, ctx.project.id, resource="correction_task", for_update=True, id=task_id
    )
    task.status = ensure_correction_task_transition(task.status, payload.status)
    task.resolved_at = (
        datetime.now(timezone.utc)
        if payload.status in (CorrectionTaskStatus.RESOLVED, CorrectionTaskStatus.DISMISSED)
        else None
    )
    if payload.note:
        task.description = f"{task.description}\n{payload.note}" if task.description else payload.note
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="correction_task.update",
        target_type="correction_task",
        target_id=task.id,
        payload={"status": payload.status.value},
    )
    db.commit()
    return ok(_correction_data(task))


class FactPushRequest(BaseModel):
    target_type: PushTargetType
    target_ref: str = Field(default="", max_length=1024)


@router.post("/facts/{fact_id}/push")
def push_fact(
    fact_id: uuid.UUID,
    payload: FactPushRequest,
    ctx: ProjectContext = Depends(require_permission("publish.execute")),
    db: Session = Depends(get_db),
) -> dict:
    """把已核准事实推到 EEAT 信源。

    只生成草稿词条或送达 webhook，不宣称对方已发布；重复推送返回原记录（created=False）。
    """
    fact = _require_fact(db, ctx.project.id, fact_id, for_update=True)
    push, created = fact_push.push_fact(
        db,
        project_id=ctx.project.id,
        fact=fact,
        target_type=payload.target_type,
        target_ref=payload.target_ref,
        actor_id=ctx.user.id,
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="fact.push",
        target_type="distribution_push",
        target_id=push.id,
        payload={
            "fact_id": str(fact.id),
            "target_type": push.target_type.value,
            "target_ref": push.target_ref,
            "status": push.status.value,
            "created": created,
        },
    )
    db.commit()
    return ok({**fact_push.push_payload(push), "created": created})


@router.get("/facts/{fact_id}/pushes")
def list_fact_pushes(
    fact_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    _require_fact(db, ctx.project.id, fact_id)
    rows, total = fact_push.page_pushes(
        db, ctx.project.id, fact_id=fact_id, page=page, page_size=page_size
    )
    return ok_page(
        [fact_push.push_payload(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/push-records")
def list_push_records(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    status: PushStatus | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    rows, total = fact_push.page_pushes(
        db, ctx.project.id, status=status, page=page, page_size=page_size
    )
    return ok_page(
        [fact_push.push_payload(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/push-records/{push_id}/retry")
def retry_push_record(
    push_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("publish.execute")),
    db: Session = Depends(get_db),
) -> dict:
    push = fact_push.retry_push(db, project_id=ctx.project.id, push_id=push_id)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="fact.push.retry",
        target_type="distribution_push",
        target_id=push.id,
        payload={"status": push.status.value, "attempt_count": push.attempt_count},
    )
    db.commit()
    return ok(fact_push.push_payload(push))
