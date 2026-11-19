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
    ManualSampleCreated,
    MonitoringExecuted,
    MonitoringDiagnosticData,
    MonitoringReanalyzeData,
    MonitoringReplayData,
    MonitoringResampleData,
    MonitoringRoundData,
    MonitoringRoundCompleteData,
    MonitoringSampleData,
    MonitoringTaskData,
    PagedEnvelope,
    SampleDetailData,
    SampleEvidenceCoverageData,
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
from app.schemas import ManualSampleCreate, RoundCreate, SampleReviewRequest
from app.services import monitoring_batch, monitoring_collection
from app.services.audit import record_audit
from app.services.brand_profile import build_vocabulary
from app.services.citation_attribution import build_published_index
from app.services.monitoring_extraction import AnswerPayload, CitationInput, apply_answer_payload
from app.services.outbox import emit_event
from app.services.state_machine import ensure_task_transition
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


def _sample_summary(row: MonitoringSample, *, evidence_count: int = 0) -> dict:
    """列表载荷：不带 raw_answer / raw_response / request_payload，避免一页几十 MB。"""
    return {
        "id": str(row.id),
        "task_id": str(row.task_id),
        "trace_id": row.trace_id,
        "status": row.status.value,
        "attempt_no": row.attempt_no,
        "sampled_at": row.sampled_at,
        "conversation_id": row.conversation_id,
        "conversation_mode": row.conversation_mode,
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
        "evidence_count": evidence_count,
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
    sample_ids = [row.id for row in rows]
    evidence_counts: dict[uuid.UUID, int] = {}
    if sample_ids:
        evidence_counts = {
            sample_id: count
            for sample_id, count in db.execute(
                select(EvidenceFile.sample_id, func.count(EvidenceFile.id))
                .where(
                    EvidenceFile.project_id == ctx.project.id,
                    EvidenceFile.sample_id.in_(sample_ids),
                )
                .group_by(EvidenceFile.sample_id)
            ).all()
        }
    return ok_page(
        [_sample_summary(row, evidence_count=evidence_counts.get(row.id, 0)) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/samples/evidence-coverage", response_model=Envelope[SampleEvidenceCoverageData])
def sample_evidence_coverage(
    ctx: ProjectContext = Depends(require_permission("monitoring.read")),
    db: Session = Depends(get_db),
) -> dict:
    """P17 采样表证据覆盖：有多少样本已有证据、哪些样本仍是 0 证据。"""
    total = db.scalar(
        select(func.count()).select_from(MonitoringSample).where(
            MonitoringSample.project_id == ctx.project.id
        )
    ) or 0
    with_evidence = db.scalar(
        select(func.count(func.distinct(EvidenceFile.sample_id))).where(
            EvidenceFile.project_id == ctx.project.id
        )
    ) or 0
    missing_rows = db.scalars(
        select(MonitoringSample.id)
        .outerjoin(EvidenceFile, EvidenceFile.sample_id == MonitoringSample.id)
        .where(
            MonitoringSample.project_id == ctx.project.id,
            EvidenceFile.id.is_(None),
        )
        .order_by(MonitoringSample.created_at, MonitoringSample.id)
        .limit(501)
    ).all()
    missing_truncated = len(missing_rows) > 500
    missing_ids = [str(row) for row in missing_rows[:500]]
    missing = max(total - with_evidence, 0)
    return ok(
        {
            "total_samples": total,
            "samples_with_evidence": with_evidence,
            "samples_missing_evidence": missing,
            "coverage_rate": round(with_evidence / total, 4) if total else None,
            "missing_sample_ids": missing_ids,
            "missing_truncated": missing_truncated,
        }
    )


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


@router.post("/rounds/{round_id}/start", response_model=Envelope[MonitoringRoundData])
def start_round(
    round_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("monitoring.execute")),
    db: Session = Depends(get_db),
) -> dict:
    row = monitoring_batch.start_round(
        db, project_id=ctx.project.id, round_id=round_id
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="monitoring.round_start",
        target_type="monitoring_round",
        target_id=row.id,
        payload={"status": row.status.value},
    )
    db.commit()
    return ok(monitoring_batch.round_payload(row))


@router.post(
    "/rounds/{round_id}/complete",
    response_model=Envelope[MonitoringRoundCompleteData],
)
def complete_round(
    round_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("monitoring.execute")),
    db: Session = Depends(get_db),
) -> dict:
    """完成轮次并在同一事务内冻结统计快照。"""
    row, snapshot, task_counts = monitoring_batch.complete_round(
        db,
        project_id=ctx.project.id,
        round_id=round_id,
        actor_id=ctx.user.id,
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="monitoring.round_complete",
        target_type="monitoring_round",
        target_id=row.id,
        payload={
            "snapshot_id": str(snapshot.id),
            "snapshot_hash": snapshot.snapshot_hash,
            "task_counts": task_counts,
        },
    )
    db.commit()
    return ok(
        {
            "round": monitoring_batch.round_payload(row),
            "snapshot_id": str(snapshot.id),
            "snapshot_hash": snapshot.snapshot_hash,
            "captured_at": snapshot.captured_at,
            "rule_version": snapshot.rule_version,
            "task_counts": task_counts,
        }
    )


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


@router.post(
    "/tasks/{task_id}/samples",
    status_code=201,
    response_model=Envelope[ManualSampleCreated],
)
def create_manual_sample(
    task_id: uuid.UUID,
    payload: ManualSampleCreate,
    ctx: ProjectContext = Depends(require_permission("monitoring.execute")),
    db: Session = Depends(get_db),
) -> dict:
    """手测样本录入：把网页端人工回答补进已有任务的证据链。

    - 只允许对终态任务补录，避免与 worker 正在跑的任务并发写样本；
    - 失败/不确定任务补录成功后收敛到 done，解除轮次完成阻塞；
    - 每次录入追加一个 attempt，不覆盖自动采样；
    - 品牌提及/可识别默认按品牌词表自动判定，也允许人工显式覆盖。
    """
    task = require_scoped_row(
        db,
        MonitoringTask,
        ctx.project.id,
        resource="monitoring_task",
        for_update=True,
        id=task_id,
    )
    if task.status not in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.UNCERTAIN):
        raise TaskRejectedError("只能给已完成、失败或不确定的任务补录手测样本")
    from_status = task.status
    entry = db.get(AiEngineEntry, task.engine_entry_id)
    if entry is None or entry.engine_id is None:
        raise TaskRejectedError("监测任务的引擎入口不存在")

    attempt_no = (
        db.scalar(
            select(func.max(MonitoringSample.attempt_no)).where(
                MonitoringSample.task_id == task.id
            )
        )
        or 0
    ) + 1
    now = datetime.now(timezone.utc)
    trace_id = task.trace_id or uuid.uuid4().hex
    task.trace_id = task.trace_id or trace_id
    raw_response = payload.raw_response or {
        "source": "manual",
        "answer_kind": payload.answer_kind.value,
    }
    request_payload = {
        "source": "manual",
        "entered_by": str(ctx.user.id),
        **({"note": payload.note} if payload.note else {}),
    }
    sample = MonitoringSample(
        project_id=ctx.project.id,
        task_id=task.id,
        attempt_no=attempt_no,
        trace_id=trace_id,
        status=SampleStatus.PENDING,
        sampled_at=payload.sampled_at or now,
        finished_at=now,
        sampling_mode=payload.sampling_mode or task.sampling_mode,
        conversation_id=uuid.uuid4().hex,
        conversation_mode="manual",
        raw_answer=payload.raw_answer.strip(),
        raw_response=raw_response,
        request_payload=request_payload,
        gateway_version="manual",
        answer_kind=payload.answer_kind,
        engine_model=entry.model_name or entry.name,
    )
    db.add(sample)
    db.flush()

    vocabulary = build_vocabulary(db, ctx.project.id)
    result = apply_answer_payload(
        db,
        sample,
        AnswerPayload(
            text=payload.raw_answer.strip(),
            raw_response=raw_response,
            brand_mentioned=payload.brand_mentioned,
            brand_identified=payload.brand_identified,
            answer_kind=payload.answer_kind,
            citations=[CitationInput(url=url) for url in payload.citation_urls],
            request_payload=request_payload,
            gateway_version="manual",
        ),
        brand_terms=vocabulary.mention_terms,
        brand_domains=vocabulary.owned_domains,
        brand_identifiers=vocabulary.identifier_terms,
        published_index=build_published_index(db, ctx.project.id),
    )
    # 手测回答是人工确认过的终态；命中口径与自动采样一致，只看 brand_mentioned。
    sample.status = SampleStatus.HIT if result["brand_mentioned"] else SampleStatus.MISS
    if task.status != TaskStatus.DONE:
        task.status = ensure_task_transition(task.status, TaskStatus.DONE)
        task.lease_owner = None
        task.lease_expires_at = None
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="monitoring.sample_create",
        target_type="monitoring_sample",
        target_id=sample.id,
        payload={
            "task_id": str(task.id),
            "attempt_no": attempt_no,
            "answer_kind": payload.answer_kind.value,
            "sampling_mode": sample.sampling_mode.value if sample.sampling_mode else None,
            "conversation_id": sample.conversation_id,
            "conversation_mode": sample.conversation_mode,
            "brand_mentioned": result["brand_mentioned"],
            "brand_identified": result["brand_identified"],
            "citation_count": result["citation_count"],
            "task_status_from": from_status.value,
            "task_status_to": task.status.value,
        },
    )
    db.commit()
    return ok(
        {
            "sample_id": str(sample.id),
            "task_id": str(task.id),
            "task_status": task.status.value,
            "attempt_no": attempt_no,
            "status": sample.status.value,
            "answer_kind": sample.answer_kind.value,
            "sampling_mode": sample.sampling_mode.value if sample.sampling_mode else None,
            "conversation_id": sample.conversation_id,
            "conversation_mode": sample.conversation_mode,
            "brand_mentioned": bool(result["brand_mentioned"]),
            "brand_identified": bool(result["brand_identified"]),
            "citation_count": result["citation_count"],
        }
    )


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
        "title": row.title,
        "position": row.position,
        "source_category": row.source_category.value if row.source_category else None,
        "page_type": row.page_type.value if row.page_type else None,
        "classification_source": (
            row.classification_source.value if row.classification_source else None
        ),
        "classification_rule_version": row.classification_rule_version,
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
        "conversation_id": sample.conversation_id,
        "conversation_mode": sample.conversation_mode,
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
        "brand_identified": sample.brand_identified,
        "brand_match_kind": sample.brand_match_kind,
        "brand_match_term": sample.brand_match_term,
        "brand_match_offset": sample.brand_match_offset,
        "brand_match_evidence": sample.brand_match_evidence,
        "brand_list_rank": sample.brand_list_rank,
        "matcher_version": sample.matcher_version,
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
    deprecated=True,
)
def replay_sample(
    sample_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("monitoring.execute")),
    db: Session = Depends(get_db),
) -> dict:
    """（已弃用）同任务再执行一次 attempt，仅用于排查引擎稳定性。

    业务上的“再抽一次”用 `/resample`，“按新规则重算”用 `/reanalyze`；
    旧 replay 会产生同任务多 attempt，不应作为日常运营入口。
    """
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


@router.post(
    "/samples/{sample_id}/resample",
    status_code=201,
    response_model=Envelope[MonitoringResampleData],
)
def resample_sample(
    sample_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("monitoring.execute")),
    db: Session = Depends(get_db),
) -> dict:
    """重采样：同一轮次、同一题目版本与入口，新建 sampling_no 的逻辑样本。

    与 replay 的区别是“再抽一次”而不是“对同一次采样重试”，会进入统计分母；
    接口只建任务并写 outbox，实际执行由 worker 完成。
    """
    result = monitoring_collection.resample_sample(
        db,
        project_id=ctx.project.id,
        sample_id=sample_id,
        actor_id=ctx.user.id,
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="monitoring.sample.resample",
        target_type="monitoring_sample",
        target_id=sample_id,
        payload={
            "new_task_id": result["task_id"],
            "sampling_no": result["sampling_no"],
        },
    )
    db.commit()
    return ok(result)


@router.post(
    "/samples/{sample_id}/reanalyze",
    status_code=200,
    response_model=Envelope[MonitoringReanalyzeData],
)
def reanalyze_sample(
    sample_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("monitoring.execute")),
    db: Session = Depends(get_db),
) -> dict:
    """重分析：不请求 AI 平台，用样本已留存答案按本轮快照重算派生字段。"""
    result = monitoring_collection.reanalyze_sample(
        db,
        project_id=ctx.project.id,
        sample_id=sample_id,
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="monitoring.sample.reanalyze",
        target_type="monitoring_sample",
        target_id=sample_id,
        payload={
            "status": result["status"],
            "brand_mentioned": result["brand_mentioned"],
            "analysis_version": result.get("analysis_version"),
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
