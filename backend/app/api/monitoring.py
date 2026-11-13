"""监测接口：读数据要 monitoring.read，触发执行要 monitoring.execute。

执行限制：只有 pending 任务可触发；running 再点一次会被 409 挡住。
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    BatchGenerateData,
    Envelope,
    MonitoringExecuted,
    MonitoringRoundData,
    MonitoringSampleData,
    MonitoringSampleDetail,
    MonitoringTaskData,
    PagedEnvelope,
    ok,
    ok_page,
)
from app.core.errors import TaskRejectedError
from app.db.session import get_db
from app.models import AiEngine, AiEngineEntry, MonitoringCitation, MonitoringSample, MonitoringTask, Question, QuestionVersion
from app.models.enums import SampleStatus, TaskStatus
from app.schemas import RoundCreate
from app.schemas.review import SampleManualReview
from app.services import monitoring_batch
from app.services.audit import record_audit
from app.services.outbox import emit_event
from app.services.project_scope import require_scoped_row
from app.services.state_machine import ensure_sample_transition, ensure_task_transition

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/monitoring",
    tags=["监测"],
    responses=COMMON_ERRORS,
)


def _sample_payload(row: MonitoringSample) -> dict:
    return {
        "id": str(row.id),
        "task_id": str(row.task_id),
        "status": row.status.value,
        "attempt_no": row.attempt_no,
        "sampled_at": row.sampled_at,
        "raw_answer": row.raw_answer,
        "raw_response": row.raw_response,
        "brand_mentioned": row.brand_mentioned,
        "failure_code": row.failure_code.value if row.failure_code else None,
        "failure_note": row.failure_note,
        "review_result": row.review_result.value if row.review_result else None,
        "review_note": row.review_note,
        "reviewed_at": row.reviewed_at,
    }


@router.get("/samples", response_model=PagedEnvelope[MonitoringSampleData])
def list_samples(
    ctx: ProjectContext = Depends(require_permission("monitoring.read")),
    db: Session = Depends(get_db),
    status: SampleStatus | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    filters = [MonitoringSample.project_id == ctx.project.id]
    if status is not None:
        filters.append(MonitoringSample.status == status)
    total = db.scalar(select(func.count()).select_from(MonitoringSample).where(*filters)) or 0
    rows = db.scalars(
        select(MonitoringSample)
        .where(*filters)
        .order_by(MonitoringSample.created_at.desc(), MonitoringSample.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page([_sample_payload(row) for row in rows], page=page, page_size=page_size, total=total)


@router.get("/samples/{sample_id}", response_model=Envelope[MonitoringSampleDetail])
def get_sample(
    sample_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("monitoring.read")),
    db: Session = Depends(get_db),
) -> dict:
    row = require_scoped_row(db, MonitoringSample, ctx.project.id, resource="monitoring_sample", id=sample_id)
    citations = db.scalars(
        select(MonitoringCitation).where(
            MonitoringCitation.project_id == ctx.project.id,
            MonitoringCitation.sample_id == row.id,
        ).order_by(MonitoringCitation.created_at, MonitoringCitation.id)
    ).all()
    return ok({
        **_sample_payload(row),
        "citations": [
            {
                "id": str(citation.id),
                "sample_id": str(citation.sample_id),
                "raw_url": citation.raw_url,
                "normalized_url": citation.normalized_url,
                "domain": citation.domain,
                "channel_id": str(citation.channel_id) if citation.channel_id else None,
                "is_brand_related": citation.is_brand_related,
                "review_status": citation.review_status.value,
                "review_note": citation.review_note,
            }
            for citation in citations
        ],
    })


@router.post("/samples/{sample_id}/manual-review", response_model=Envelope[MonitoringSampleData])
def manual_review_sample(
    sample_id: uuid.UUID,
    payload: SampleManualReview,
    ctx: ProjectContext = Depends(require_permission("evidence.review")),
    db: Session = Depends(get_db),
) -> dict:
    sample = require_scoped_row(
        db, MonitoringSample, ctx.project.id, resource="monitoring_sample", for_update=True, id=sample_id
    )
    if sample.status != SampleStatus.MANUAL_REVIEW or not (sample.raw_answer or "").strip():
        raise TaskRejectedError("只有含原始回答的待人工复核样本可判定")
    target = SampleStatus(payload.result.value)
    sample.status = ensure_sample_transition(sample.status, target)
    sample.brand_mentioned = target == SampleStatus.HIT
    sample.review_result = payload.result
    sample.review_note = payload.note
    sample.reviewed_by = ctx.user.id
    sample.reviewed_at = datetime.now(timezone.utc)
    sample.finished_at = sample.finished_at or sample.reviewed_at
    task = require_scoped_row(db, MonitoringTask, ctx.project.id, resource="monitoring_task", id=sample.task_id)
    if task.status == TaskStatus.RUNNING:
        task.status = ensure_task_transition(task.status, TaskStatus.DONE)
    record_audit(
        db, project_id=ctx.project.id, actor_id=ctx.user.id,
        action="monitoring.sample_manual_review", target_type="monitoring_sample", target_id=sample.id,
        payload={"result": payload.result.value},
    )
    db.commit()
    return ok(_sample_payload(sample))


@router.get("/rounds", response_model=PagedEnvelope[MonitoringRoundData])
def list_rounds(
    ctx: ProjectContext = Depends(require_permission("monitoring.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
) -> dict:
    rows, total = monitoring_batch.list_rounds(
        db, project_id=ctx.project.id, page=page, page_size=page_size
    )
    return ok_page(rows, page=page, page_size=page_size, total=total)


@router.post("/rounds", status_code=201, response_model=Envelope[MonitoringRoundData])
def create_round(
    payload: RoundCreate,
    ctx: ProjectContext = Depends(require_permission("monitoring.execute")),
    db: Session = Depends(get_db),
) -> dict:
    row = monitoring_batch.create_round(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        name=payload.name,
        is_baseline=payload.is_baseline,
        planned_at=payload.planned_at,
    )
    db.commit()
    return ok(monitoring_batch.round_payload(row))


@router.post(
    "/rounds/{round_id}/tasks/batch",
    response_model=Envelope[BatchGenerateData],
)
def batch_generate_tasks(
    round_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("monitoring.execute")),
    db: Session = Depends(get_db),
) -> dict:
    result = monitoring_batch.generate_tasks(
        db,
        project_id=ctx.project.id,
        round_id=round_id,
        actor_id=ctx.user.id,
    )
    db.commit()
    return ok(result)


@router.get("/tasks", response_model=PagedEnvelope[MonitoringTaskData])
def list_tasks(
    ctx: ProjectContext = Depends(require_permission("monitoring.read")),
    db: Session = Depends(get_db),
    round_id: uuid.UUID | None = None,
    status: TaskStatus | None = None,
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
) -> dict:
    filters = [MonitoringTask.project_id == ctx.project.id]
    if round_id is not None:
        filters.append(MonitoringTask.round_id == round_id)
    if status is not None:
        filters.append(MonitoringTask.status == status)

    total = db.scalar(select(func.count()).select_from(MonitoringTask).where(*filters)) or 0
    rows = db.execute(
        select(MonitoringTask, Question, AiEngine)
        .join(QuestionVersion, QuestionVersion.id == MonitoringTask.question_version_id)
        .join(Question, Question.id == QuestionVersion.question_id)
        .join(AiEngineEntry, AiEngineEntry.id == MonitoringTask.engine_entry_id)
        .join(AiEngine, AiEngine.id == AiEngineEntry.engine_id)
        .where(*filters, QuestionVersion.project_id == ctx.project.id, Question.project_id == ctx.project.id)
        .order_by(MonitoringTask.created_at.desc(), MonitoringTask.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page(
        [
            {
                "id": str(row.id),
                "round_id": str(row.round_id),
                "status": row.status,
                "sampling_no": row.sampling_no,
                "question_code": question.code,
                "question_title": question.title,
                "engine_code": engine.code,
                "engine_name": engine.name,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
            for row, question, engine in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post(
    "/tasks/{task_id}/execute",
    status_code=202,
    response_model=Envelope[MonitoringExecuted],
)
def execute_task(
    task_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("monitoring.execute")),
    db: Session = Depends(get_db),
) -> dict:
    task = require_scoped_row(
        db, MonitoringTask, ctx.project.id, resource="monitoring_task", id=task_id
    )
    # 统一状态迁移校验：终态/非法状态在这里明确 409；随后原子条件更新只负责并发抢占。
    ensure_task_transition(task.status, TaskStatus.RUNNING)

    # 原子条件更新：只有仍为 pending 的行会被抢到，避免并发请求同时读到 pending
    # 后都改成 running、重复写审计。
    result = db.execute(
        update(MonitoringTask)
        .where(
            MonitoringTask.id == task.id,
            MonitoringTask.project_id == ctx.project.id,
            MonitoringTask.status == TaskStatus.PENDING,
        )
        .values(status=TaskStatus.RUNNING)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise TaskRejectedError("仅 pending 任务可触发，任务已被其他请求占用或状态不允许")

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="monitoring.execute",
        target_type="monitoring_task",
        target_id=task.id,
        payload={"from": TaskStatus.PENDING.value, "to": TaskStatus.RUNNING.value},
    )
    # 状态与事件同事务：只有提交成功，outbox dispatcher 才看得到这条事件。
    emit_event(
        db,
        project_id=ctx.project.id,
        topic="monitoring.task.execute",
        payload={
            "project_id": str(ctx.project.id),
            "task_id": str(task.id),
            "round_id": str(task.round_id),
        },
    )
    db.commit()
    return ok({"task_id": str(task.id), "status": TaskStatus.RUNNING.value})
