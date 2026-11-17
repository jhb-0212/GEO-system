"""监测接口：读数据要 monitoring.read，触发执行要 monitoring.execute。

执行限制：只有 pending 任务可触发；running 再点一次会被 409 挡住。
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_any_permission, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    BatchGenerateData,
    Envelope,
    MonitoringExecuted,
    MonitoringDiagnosticData,
    MonitoringReplayData,
    MonitoringRoundData,
    MonitoringSampleData,
    MonitoringTaskData,
    PagedEnvelope,
    SampleDetailData,
    SampleReviewData,
    TraceChainData,
    ok,
    ok_page,
)
from app.core.errors import TaskRejectedError
from app.db.session import get_db
from app.models import (
    AiEngine,
    AiEngineEntry,
    Channel,
    EvidenceFile,
    MonitoringCitation,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.models.enums import FailureCode, ReviewResult, SampleStatus, TaskStatus
from app.schemas import RoundCreate, SampleReviewRequest
from app.services import monitoring_batch, monitoring_collection
from app.services.audit import record_audit
from app.services.outbox import emit_event
from app.services.project_scope import require_scoped_row
from app.services.state_machine import ensure_sample_transition, ensure_task_transition
from app.services.trace_chain import trace_detail

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/monitoring",
    tags=["监测"],
    responses=COMMON_ERRORS,
)


def _answer_excerpt(text: str | None, limit: int = 200) -> str | None:
    """列表只用摘要：压缩空白并截断，完整回答由单条详情接口返回。"""
    if not text:
        return None
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else f"{compact[:limit]}..."


def _sample_payload(row: MonitoringSample) -> dict:
    return {
        "id": str(row.id),
        "task_id": str(row.task_id),
        "trace_id": row.trace_id,
        "status": row.status.value,
        "attempt_no": row.attempt_no,
        "sampled_at": row.sampled_at,
        "raw_answer": row.raw_answer,
        "raw_response": row.raw_response,
        "request_payload": row.request_payload,
        "latency_ms": row.latency_ms,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "total_tokens": row.total_tokens,
        "estimated_cost_cny": (
            float(row.estimated_cost_cny) if row.estimated_cost_cny is not None else None
        ),
        "gateway_version": row.gateway_version,
        "brand_mentioned": row.brand_mentioned,
        "failure_code": row.failure_code.value if row.failure_code else None,
        "failure_note": row.failure_note,
        "review_result": row.review_result.value if row.review_result else None,
        "review_note": row.review_note,
        "reviewed_at": row.reviewed_at,
    }


def _sample_summary(row: MonitoringSample) -> dict:
    """列表载荷：不带 raw_answer / raw_response / request_payload，避免一页几十 MB。"""
    return {
        "id": str(row.id),
        "task_id": str(row.task_id),
        "trace_id": row.trace_id,
        "status": row.status.value,
        "attempt_no": row.attempt_no,
        "sampled_at": row.sampled_at,
        "answer_excerpt": _answer_excerpt(row.raw_answer),
        "latency_ms": row.latency_ms,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "total_tokens": row.total_tokens,
        "estimated_cost_cny": (
            float(row.estimated_cost_cny) if row.estimated_cost_cny is not None else None
        ),
        "gateway_version": row.gateway_version,
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
    return ok_page([_sample_summary(row) for row in rows], page=page, page_size=page_size, total=total)


@router.get("/diagnostics", response_model=PagedEnvelope[MonitoringDiagnosticData])
def list_diagnostics(
    ctx: ProjectContext = Depends(require_any_permission("monitoring.execute", "project.member.manage")),
    db: Session = Depends(get_db),
    status: SampleStatus = Query(SampleStatus.FAILED, description="样本状态，默认只看失败"),
    failure_code: FailureCode | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    """内部排障：失败样本 + 任务状态 + 引擎/问题 + 重试次数/耗时/trace。"""
    filters = [
        MonitoringSample.project_id == ctx.project.id,
        MonitoringSample.status == status,
    ]
    if failure_code is not None:
        filters.append(MonitoringSample.failure_code == failure_code)

    total = db.scalar(select(func.count()).select_from(MonitoringSample).where(*filters)) or 0
    rows = db.execute(
        select(MonitoringSample, MonitoringTask, Question, AiEngine)
        .join(MonitoringTask, MonitoringTask.id == MonitoringSample.task_id)
        .join(QuestionVersion, QuestionVersion.id == MonitoringTask.question_version_id)
        .join(Question, Question.id == QuestionVersion.question_id)
        .join(AiEngineEntry, AiEngineEntry.id == MonitoringTask.engine_entry_id)
        .join(AiEngine, AiEngine.id == AiEngineEntry.engine_id)
        .where(*filters)
        .order_by(
            MonitoringSample.finished_at.desc().nulls_last(),
            MonitoringSample.created_at.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items = []
    for sample, task, question, engine in rows:
        items.append(
            {
                "sample_id": str(sample.id),
                "task_id": str(task.id),
                "trace_id": sample.trace_id or task.trace_id,
                "sample_status": sample.status.value,
                "task_status": task.status.value,
                "attempt_no": sample.attempt_no,
                "retry_count": max(sample.attempt_no - 1, 0),
                "sampled_at": sample.sampled_at,
                "finished_at": sample.finished_at,
                "failure_code": sample.failure_code.value if sample.failure_code else None,
                "failure_note": sample.failure_note,
                "latency_ms": sample.latency_ms,
                "total_tokens": sample.total_tokens,
                "estimated_cost_cny": (
                    float(sample.estimated_cost_cny)
                    if sample.estimated_cost_cny is not None
                    else None
                ),
                "gateway_version": sample.gateway_version,
                "engine_code": engine.code,
                "engine_name": engine.name,
                "question_code": question.code,
                "question_title": question.title,
            }
        )
    return ok_page(items, page=page, page_size=page_size, total=total)


@router.get("/traces/{trace_id}", response_model=Envelope[TraceChainData])
def get_trace_chain(
    trace_id: str,
    ctx: ProjectContext = Depends(require_any_permission("monitoring.execute", "project.member.manage")),
    db: Session = Depends(get_db),
) -> dict:
    """跨实体链路：轮次 → 任务 → 样本 → 引用 → 内容版本 → 发布任务。"""
    return ok(trace_detail(db, project_id=ctx.project.id, trace_id=trace_id))


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
                "trace_id": row.trace_id,
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


# 复核结论 → 样本目标状态；人工复核只能归入 hit/miss（工单 B5）。
_REVIEW_RESULT_TO_SAMPLE_STATUS: dict[ReviewResult, SampleStatus] = {
    ReviewResult.HIT: SampleStatus.HIT,
    ReviewResult.MISS: SampleStatus.MISS,
}


def _citation_brief(row: MonitoringCitation, channel: Channel | None = None) -> dict:
    return {
        "citation_id": str(row.id),
        "trace_id": row.trace_id,
        "raw_url": row.raw_url,
        "normalized_url": row.normalized_url,
        "domain": row.domain,
        "channel_id": str(row.channel_id) if row.channel_id else None,
        "channel_name": channel.name if channel is not None else None,
        "channel_category": str(channel.category) if channel is not None else None,
        "citation_usage": row.citation_usage.value if row.citation_usage else None,
        "is_brand_related": row.is_brand_related,
        "review_status": row.review_status.value,
    }


def _sample_detail(
    sample: MonitoringSample,
    citations: list[MonitoringCitation],
    evidence: list[EvidenceFile],
    channel_map: dict[uuid.UUID, Channel] | None = None,
) -> dict:
    channel_map = channel_map or {}
    return {
        "id": str(sample.id),
        "task_id": str(sample.task_id),
        "trace_id": sample.trace_id,
        "attempt_no": sample.attempt_no,
        "status": sample.status.value,
        "sampled_at": sample.sampled_at,
        "finished_at": sample.finished_at,
        "sampling_mode": sample.sampling_mode.value,
        "raw_answer": sample.raw_answer,
        "request_payload": sample.request_payload,
        "latency_ms": sample.latency_ms,
        "prompt_tokens": sample.prompt_tokens,
        "completion_tokens": sample.completion_tokens,
        "total_tokens": sample.total_tokens,
        "estimated_cost_cny": (
            float(sample.estimated_cost_cny) if sample.estimated_cost_cny is not None else None
        ),
        "gateway_version": sample.gateway_version,
        "brand_mentioned": sample.brand_mentioned,
        "engine_model": sample.engine_model,
        "model_version": sample.model_version,
        "country_code": sample.country_code,
        "language": sample.language,
        "failure_code": sample.failure_code.value if sample.failure_code else None,
        "failure_note": sample.failure_note,
        "review_result": sample.review_result.value if sample.review_result else None,
        "review_note": sample.review_note,
        "reviewed_at": sample.reviewed_at,
        "citations": [_citation_brief(c, channel_map.get(c.channel_id)) for c in citations],
        "evidence_files": [
            {
                "evidence_id": str(e.id),
                "file_type": e.file_type.value,
                "content_type": e.content_type,
                "byte_size": e.byte_size,
                "checksum": e.checksum,
            }
            for e in evidence
        ],
    }


@router.post(
    "/samples/{sample_id}/replay",
    status_code=201,
    response_model=Envelope[MonitoringReplayData],
)
def replay_sample(
    sample_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("monitoring.execute")),
    db: Session = Depends(get_db),
) -> dict:
    """用留存请求体回放样本；旧样本无请求体时退回当前题目重建请求。"""
    result = monitoring_collection.replay_sample(
        db,
        project_id=ctx.project.id,
        sample_id=sample_id,
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="monitoring.sample.replay",
        target_type="monitoring_sample",
        target_id=sample_id,
        payload={
            "new_sample_id": result["sample_id"],
            "trace_id": result.get("trace_id"),
            "used_stored_request": result.get("used_stored_request", False),
        },
    )
    db.commit()
    return ok(result)


@router.get("/samples/{sample_id}", response_model=Envelope[SampleDetailData])
def get_sample(
    sample_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("monitoring.read")),
    db: Session = Depends(get_db),
) -> dict:
    sample = require_scoped_row(
        db,
        MonitoringSample,
        ctx.project.id,
        resource="monitoring_sample",
        id=sample_id,
    )
    citations = db.scalars(
        select(MonitoringCitation)
        .where(MonitoringCitation.sample_id == sample.id)
        .order_by(MonitoringCitation.created_at)
    ).all()
    evidence = db.scalars(
        select(EvidenceFile)
        .where(EvidenceFile.sample_id == sample.id)
        .order_by(EvidenceFile.created_at)
    ).all()
    channel_ids = {c.channel_id for c in citations if c.channel_id is not None}
    channel_map = {}
    if channel_ids:
        channel_map = {
            row.id: row
            for row in db.scalars(select(Channel).where(Channel.id.in_(channel_ids))).all()
        }
    return ok(_sample_detail(sample, list(citations), list(evidence), channel_map))


@router.post(
    "/samples/{sample_id}/manual-review",
    response_model=Envelope[SampleReviewData],
)
def review_sample(
    sample_id: uuid.UUID,
    payload: SampleReviewRequest,
    # B5 权限码按 C 拍板复用 evidence.review（reviewer / project_admin 持有），不新增 sample.review。
    ctx: ProjectContext = Depends(require_permission("evidence.review")),
    db: Session = Depends(get_db),
) -> dict:
    sample = require_scoped_row(
        db,
        MonitoringSample,
        ctx.project.id,
        resource="monitoring_sample",
        id=sample_id,
        for_update=True,
    )
    if sample.status != SampleStatus.MANUAL_REVIEW or not (sample.raw_answer or "").strip():
        raise TaskRejectedError("只有含原始回答的待人工复核样本可判定")
    target_status = _REVIEW_RESULT_TO_SAMPLE_STATUS[payload.review_result]
    # 状态机校验：终态 hit/miss/failed 不可再复核；非法迁移明确 409。
    ensure_sample_transition(sample.status, target_status)
    from_status = sample.status

    sample.status = target_status
    sample.review_result = payload.review_result
    sample.review_note = payload.review_note
    sample.reviewed_by = ctx.user.id
    sample.reviewed_at = datetime.now(timezone.utc)

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="monitoring.sample_review",
        target_type="monitoring_sample",
        target_id=sample.id,
        payload={
            "from": from_status.value,
            "to": target_status.value,
            "review_result": payload.review_result.value,
        },
    )
    db.commit()
    return ok(
        {
            "sample_id": str(sample.id),
            "status": sample.status.value,
            "review_result": sample.review_result.value,
        }
    )
