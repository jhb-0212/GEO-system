"""监测自动采集链：按轮次生成任务、样本抢占、适配器调用与失败归档。

分工：
- `plan_round_tasks`：调度器可重复执行，按唯一键幂等建 pending 任务；不生成轮次；
- `schedule_active_rounds`：扫描 active 项目 + planning/running 轮次，建任务并为新建任务写 outbox；
- `execute_task`：Worker/CLI 执行单个任务，按样本 `(task_id, attempt_no)` 唯一约束抢占，
  真实适配器通过 `AnswerAdapter` 注入，未接适配器时落 `access_blocked`，不伪造 hit/miss；
- `EngineRateLimiter`：每引擎每分钟限流，限流不落样本，交给 Worker 重试。
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

import redis
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ProjectAccessError, TaskRejectedError
from app.models import (
    AiEngine,
    AiEngineEntry,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Project,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    EngineProtocol,
    FailureCode,
    ProjectStatus,
    QuestionStatus,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    TaskStatus,
)
from app.services.brand_profile import build_vocabulary
from app.services.engine_gateway import GATEWAY_VERSION, EngineGateway
from app.services.monitoring_extraction import (
    AnswerPayload,
    apply_answer_payload,
)
from app.services.outbox import emit_event
from app.services.state_machine import ensure_sample_transition, ensure_task_transition

logger = logging.getLogger(__name__)


class CollectionFailure(Exception):
    """适配器/限流失败；`retryable` 决定 Worker 是否重试。"""

    def __init__(
        self,
        message: str,
        *,
        failure_code: FailureCode,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.failure_code = failure_code
        self.retryable = retryable


class AccessBlockedFailure(CollectionFailure):
    def __init__(self, message: str = "入口无可调用凭据；未发起真实请求") -> None:
        super().__init__(message, failure_code=FailureCode.ACCESS_BLOCKED, retryable=False)


class RateLimitedFailure(CollectionFailure):
    def __init__(self, message: str = "引擎触发本地限流") -> None:
        super().__init__(message, failure_code=FailureCode.RATE_LIMITED, retryable=True)


class TransientCollectionFailure(CollectionFailure):
    def __init__(self, message: str, failure_code: FailureCode = FailureCode.TIMEOUT) -> None:
        super().__init__(message, failure_code=failure_code, retryable=True)


class AnswerAdapter(Protocol):
    def collect(self, task: MonitoringTask) -> AnswerPayload:
        """返回标准答案；拿不到就抛 CollectionFailure。"""


class UnconfiguredAdapter:
    """本期没有真实引擎凭据/适配器时的默认实现：明确失败，不伪造答案。"""

    def collect(self, task: MonitoringTask) -> AnswerPayload:
        raise AccessBlockedFailure("引擎适配器未配置；未发起真实请求")


def build_entry_adapter(db: Session, entry: AiEngineEntry | None) -> AnswerAdapter:
    """按入口协议选适配器；未接协议继续明确失败，不伪造答案。"""
    if entry is None:
        return UnconfiguredAdapter()
    if entry.protocol == EngineProtocol.YUANBAO_SEARCH:
        from app.services.yuanbao_search_adapter import build_yuanbao_adapter

        return build_yuanbao_adapter(
            db,
            credential_ref=entry.credential_ref,
            entry_url=entry.entry_url,
        )
    if entry.protocol == EngineProtocol.DEEPSEEK_WEBSEARCH:
        from app.services.deepseek_websearch_adapter import (
            build_deepseek_websearch_adapter,
        )

        return build_deepseek_websearch_adapter(
            db,
            entry_url=entry.entry_url,
            credential_ref=entry.credential_ref,
            bridge_url_fallback=settings.deepseek_websearch_bridge_url,
            timeout_seconds=settings.deepseek_websearch_timeout_seconds,
        )
    if entry.protocol != EngineProtocol.OPENAI_COMPATIBLE:
        return UnconfiguredAdapter()
    if not entry.entry_url:
        raise AccessBlockedFailure("openai_compatible 入口未配置 entry_url")
    if not entry.model_name:
        raise AccessBlockedFailure("openai_compatible 入口未配置 model_name")

    api_key = ""
    if entry.credential_ref:
        api_key = os.getenv(entry.credential_ref, "").strip()
        if not api_key:
            raise AccessBlockedFailure(
                f"环境变量 {entry.credential_ref} 未配置，入口无法调用"
            )

    # 延迟导入，避免 monitoring_collection ←→ 适配器模块循环依赖。
    from app.services.openai_compatible_adapter import OpenAICompatibleAdapter

    return OpenAICompatibleAdapter(
        db,
        base_url=entry.entry_url,
        model=entry.model_name,
        api_key=api_key,
    )


class LazyEntryAdapter:
    """备用入口延迟到真正需要时才建客户端；避免主入口成功也泄漏连接。"""

    def __init__(self, db: Session, entry: AiEngineEntry) -> None:
        self._db = db
        self._entry = entry
        self.last_request_payload: dict[str, Any] | None = None

    def _build(self) -> AnswerAdapter:
        return build_entry_adapter(self._db, self._entry)

    def collect(self, task: MonitoringTask) -> AnswerPayload:
        adapter = self._build()
        try:
            return adapter.collect(task)
        finally:
            self.last_request_payload = getattr(adapter, "last_request_payload", None)
            close = getattr(adapter, "close", None)
            if callable(close):
                close()

    def collect_with_request(
        self,
        task: MonitoringTask,
        request_payload: dict[str, Any],
    ) -> AnswerPayload:
        adapter = self._build()
        try:
            return adapter.collect_with_request(task, request_payload)  # type: ignore[attr-defined]
        finally:
            self.last_request_payload = getattr(adapter, "last_request_payload", None)
            close = getattr(adapter, "close", None)
            if callable(close):
                close()


def build_fallback_adapters(db: Session, primary: AiEngineEntry | None) -> list[AnswerAdapter]:
    """同一引擎下的备用入口；没有第二个入口时返回空列表，不伪造降级。"""
    if primary is None:
        return []
    entries = db.scalars(
        select(AiEngineEntry)
        .where(
            AiEngineEntry.engine_id == primary.engine_id,
            AiEngineEntry.is_active.is_(True),
            AiEngineEntry.id != primary.id,
        )
        .order_by(AiEngineEntry.created_at, AiEngineEntry.id)
    ).all()
    return [LazyEntryAdapter(db, entry) for entry in entries]


class EngineRateLimiter:
    """每引擎每分钟滑动窗口限流；Redis 故障时放行并告警，不阻断采集。"""

    def __init__(
        self,
        client: redis.Redis | None = None,
        *,
        limit_per_minute: int | None = None,
    ) -> None:
        self._client = client
        self._explicit_limit = limit_per_minute
        self.limit = max(1, int(limit_per_minute or settings.monitoring_engine_rate_limit_per_minute))

    def _limit_for(self, engine_code: str) -> int:
        """网页端采集（浏览器登录态）单独取更保守的上限，避免触发平台风控。"""
        if self._explicit_limit is None and "websearch" in engine_code:
            return max(1, int(settings.monitoring_websearch_rate_limit_per_minute))
        return self.limit

    def _redis(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        return self._client

    def allow(self, engine_code: str, *, now: datetime | None = None) -> bool:
        moment = now or datetime.now(timezone.utc)
        key = f"geo:monitoring:rate:{engine_code}:{int(moment.timestamp() // 60)}"
        limit = self._limit_for(engine_code)
        try:
            count = int(self._redis().incr(key))
            if count == 1:
                self._redis().expire(key, 90)
            return count <= limit
        except redis.RedisError:
            logger.warning(
                "monitoring rate limit unavailable; allow request",
                extra={"fields": {"engine_code": engine_code}},
            )
            return True


def _active_engine_entries(db: Session) -> list[tuple[AiEngine, AiEngineEntry]]:
    rows = db.execute(
        select(AiEngine, AiEngineEntry)
        .join(AiEngineEntry, AiEngineEntry.engine_id == AiEngine.id)
        .where(AiEngine.is_active.is_(True), AiEngineEntry.is_active.is_(True))
        .order_by(AiEngine.code, AiEngineEntry.created_at, AiEngineEntry.id)
    ).all()
    picked: dict[uuid.UUID, tuple[AiEngine, AiEngineEntry]] = {}
    for engine, entry in rows:
        picked.setdefault(engine.id, (engine, entry))
    return list(picked.values())


def _active_question_versions(
    db: Session, project_id: uuid.UUID
) -> list[tuple[Question, QuestionVersion]]:
    rows = db.execute(
        select(Question, QuestionVersion)
        .join(
            QuestionVersion,
            (QuestionVersion.question_id == Question.id)
            & (QuestionVersion.version_no == Question.current_version_no),
        )
        .where(
            Question.project_id == project_id,
            QuestionVersion.project_id == project_id,
            Question.status == QuestionStatus.ACTIVE,
        )
        .order_by(Question.code)
    ).all()
    return [(question, version) for question, version in rows]


def plan_round_tasks(
    db: Session,
    *,
    project_id: uuid.UUID,
    round_id: uuid.UUID,
    sampling_no: int = 1,
    sampling_mode: SamplingMode = SamplingMode.SEARCH_ON,
) -> dict[str, Any]:
    """按轮次幂等建 pending 任务；锁轮次行，不锁项目行。"""
    if sampling_no < 1:
        raise ValueError("sampling_no must be >= 1")

    round_row = db.scalar(
        select(MonitoringRound)
        .where(
            MonitoringRound.project_id == project_id,
            MonitoringRound.id == round_id,
        )
        .with_for_update()
    )
    if round_row is None:
        raise ProjectAccessError("monitoring_round not found in this project")

    questions = _active_question_versions(db, project_id)
    engines = _active_engine_entries(db)
    skipped_reason: str | None = None
    if not questions:
        skipped_reason = "no_active_question"
    elif not engines:
        skipped_reason = "engine_entries_insufficient"

    created: list[MonitoringTask] = []
    existing_count = 0
    if skipped_reason is None:
        for question, version in questions:
            for _engine, entry in engines:
                task = db.scalar(
                    select(MonitoringTask).where(
                        MonitoringTask.round_id == round_id,
                        MonitoringTask.question_version_id == version.id,
                        MonitoringTask.engine_entry_id == entry.id,
                        MonitoringTask.sampling_no == sampling_no,
                    )
                )
                if task is not None:
                    existing_count += 1
                    continue
                task = MonitoringTask(
                    project_id=project_id,
                    round_id=round_id,
                    question_version_id=version.id,
                    engine_entry_id=entry.id,
                    sampling_no=sampling_no,
                    sampling_mode=sampling_mode,
                    status=TaskStatus.PENDING,
                )
                db.add(task)
                created.append(task)
        db.flush()

    return {
        "project_id": str(project_id),
        "round_id": str(round_id),
        "question_count": len(questions),
        "engine_count": len(engines),
        "created_task_ids": [str(task.id) for task in created],
        "existing_task_count": existing_count,
        "skipped_reason": skipped_reason,
    }


def schedule_active_rounds(
    db: Session,
    *,
    project_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """扫描 active 项目 + 可执行轮次，建任务并给新任务写 outbox 事件。"""
    project_stmt = select(Project).where(Project.status == ProjectStatus.ACTIVE)
    if project_id is not None:
        project_stmt = project_stmt.where(Project.id == project_id)
    projects = db.scalars(project_stmt.order_by(Project.code)).all()
    project_count = 0
    round_count = 0
    created_count = 0
    skipped: list[dict[str, str]] = []

    for project in projects:
        rounds = db.scalars(
            select(MonitoringRound)
            .where(
                MonitoringRound.project_id == project.id,
                MonitoringRound.status.in_((RoundStatus.PLANNING, RoundStatus.RUNNING)),
            )
            .order_by(MonitoringRound.seq)
        ).all()
        project_count += 1
        for round_row in rounds:
            round_count += 1
            result = plan_round_tasks(
                db,
                project_id=project.id,
                round_id=round_row.id,
            )
            if result["skipped_reason"]:
                skipped.append(
                    {
                        "project_id": str(project.id),
                        "round_id": str(round_row.id),
                        "reason": result["skipped_reason"],
                    }
                )
                continue
            task_ids = result["created_task_ids"]
            created_count += len(task_ids)
            for task_id in task_ids:
                emit_event(
                    db,
                    project_id=project.id,
                    topic="monitoring.task.execute",
                    payload={
                        "project_id": str(project.id),
                        "task_id": task_id,
                        "round_id": str(round_row.id),
                    },
                )
        db.flush()

    return {
        "project_count": project_count,
        "round_count": round_count,
        "created_task_count": created_count,
        "skipped": skipped,
    }


def _sample_metadata(
    task: MonitoringTask,
    entry: AiEngineEntry | None,
    engine: AiEngine | None,
) -> dict[str, str | None]:
    return {
        "engine_model": engine.name if engine else None,
        "model_version": entry.name if entry else None,
        "country_code": "CN",
        "language": "zh",
    }


def _claim_sample(
    db: Session,
    task: MonitoringTask,
    entry: AiEngineEntry | None,
    engine: AiEngine | None,
    *,
    now: datetime,
) -> MonitoringSample | None:
    """用 `(task_id, attempt_no)` 唯一约束抢占样本；抢不到返回 None。"""
    attempt_no = int(
        db.scalar(
            select(func.coalesce(func.max(MonitoringSample.attempt_no), 0)).where(
                MonitoringSample.task_id == task.id
            )
        )
        or 0
    ) + 1
    metadata = _sample_metadata(task, entry, engine)
    sample = MonitoringSample(
        project_id=task.project_id,
        task_id=task.id,
        attempt_no=attempt_no,
        trace_id=task.trace_id,
        status=SampleStatus.RUNNING,
        sampled_at=now,
        sampling_mode=task.sampling_mode,
        **metadata,
    )
    try:
        with db.begin_nested():
            db.add(sample)
            db.flush()
    except IntegrityError:
        return None
    return sample


def _mark_failure(
    sample: MonitoringSample,
    failure: CollectionFailure,
) -> None:
    sample.status = ensure_sample_transition(sample.status, SampleStatus.FAILED)
    sample.failure_code = failure.failure_code
    sample.failure_note = str(failure)
    sample.finished_at = datetime.now(timezone.utc)


def execute_task(
    db: Session,
    *,
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    adapter: AnswerAdapter | None = None,
    rate_limiter: EngineRateLimiter | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """执行单个任务；成功/终态失败返回落库结果，可重试失败抛 CollectionFailure。"""
    task = db.scalar(
        select(MonitoringTask).where(
            MonitoringTask.project_id == project_id,
            MonitoringTask.id == task_id,
        )
    )
    if task is None:
        raise ProjectAccessError("monitoring_task not found in this project")
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectAccessError("project not found")
    if task.status in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED):
        return {
            "task_id": str(task.id),
            "status": task.status.value,
            "skipped": "task already terminal",
        }
    # 品牌口径统一从项目品牌实体取，未配置时回退到项目名/项目 code（历史口径不变）。
    vocabulary = build_vocabulary(db, project_id, project=project)

    if task.status == TaskStatus.PENDING:
        task.status = ensure_task_transition(task.status, TaskStatus.RUNNING)
        db.flush()
    elif task.status != TaskStatus.RUNNING:
        ensure_task_transition(task.status, TaskStatus.RUNNING)

    # 老任务没有 trace_id 时补一个，样本/引用都沿用它，保证排障可串。
    if not task.trace_id:
        task.trace_id = uuid.uuid4().hex
        db.flush()

    entry = db.get(AiEngineEntry, task.engine_entry_id)
    engine = db.get(AiEngine, entry.engine_id) if entry else None
    if rate_limiter is not None and engine is not None:
        if not rate_limiter.allow(engine.code, now=now):
            raise RateLimitedFailure(f"引擎 {engine.code} 超过每分钟调用上限")

    sample = _claim_sample(
        db,
        task,
        entry,
        engine,
        now=now or datetime.now(timezone.utc),
    )
    if sample is None:
        return {
            "task_id": str(task.id),
            "status": task.status.value,
            "skipped": "sample already claimed",
        }

    try:
        injected_adapter = adapter is not None
        adapter = adapter or build_entry_adapter(db, entry)
        fallback_adapters = [] if injected_adapter else build_fallback_adapters(db, entry)
        gateway = EngineGateway(
            adapter,
            input_price_cny_per_million=(
                settings.deepseek_input_price_cny_per_million
                if engine is not None and engine.code == "deepseek"
                else None
            ),
            output_price_cny_per_million=(
                settings.deepseek_output_price_cny_per_million
                if engine is not None and engine.code == "deepseek"
                else None
            ),
        )
        payload = gateway.collect(
            task,
            trace_id=task.trace_id,
            fallback_adapters=fallback_adapters,
            max_attempts=settings.monitoring_gateway_max_attempts,
            retry_backoff_seconds=settings.monitoring_gateway_retry_backoff_seconds,
        )
    except CollectionFailure as failure:
        sample.request_payload = getattr(failure, "request_payload", None)
        sample.latency_ms = getattr(failure, "latency_ms", None)
        sample.gateway_version = GATEWAY_VERSION
        _mark_failure(sample, failure)
        if not failure.retryable:
            task.status = ensure_task_transition(task.status, TaskStatus.FAILED)
        db.flush()
        if failure.retryable:
            raise
        return {
            "task_id": str(task.id),
            "sample_id": str(sample.id),
            "status": "failed",
            "failure_code": failure.failure_code.value,
        }
    except Exception as exc:  # 适配器未归一化的异常不静默成功
        failure = TransientCollectionFailure(str(exc), failure_code=FailureCode.OTHER)
        setattr(failure, "request_payload", getattr(exc, "request_payload", None))
        setattr(failure, "latency_ms", getattr(exc, "latency_ms", None))
        sample.request_payload = getattr(failure, "request_payload", None)
        sample.latency_ms = getattr(failure, "latency_ms", None)
        sample.gateway_version = GATEWAY_VERSION
        _mark_failure(sample, failure)
        db.flush()
        raise failure from exc

    result = apply_answer_payload(
        db,
        sample,
        payload,
        brand_terms=vocabulary.mention_terms,
        brand_domains=vocabulary.owned_domains,
        brand_identifiers=vocabulary.identifier_terms,
    )
    sample.status = ensure_sample_transition(
        SampleStatus.RUNNING,
        SampleStatus.HIT if result["brand_mentioned"] else SampleStatus.MISS,
    )
    sample.finished_at = datetime.now(timezone.utc)
    task.status = ensure_task_transition(task.status, TaskStatus.DONE)
    db.flush()
    return {
        "task_id": str(task.id),
        "sample_id": str(sample.id),
        "status": sample.status.value,
        "brand_mentioned": result["brand_mentioned"],
        "brand_identified": result["brand_identified"],
        "citation_count": result["citation_count"],
        "competitor_mention_count": result["competitor_mention_count"],
    }


def replay_sample(
    db: Session,
    *,
    project_id: uuid.UUID,
    sample_id: uuid.UUID,
    adapter: AnswerAdapter | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """用样本留存的请求体新建一次 attempt；不改原任务状态，不伪造成功。

    没有留存请求体（例如网关上线前的旧样本）时退回按当前题目重建请求，
    返回值 `used_stored_request=false`，避免把“换题重跑”误报成回放。
    """
    source = db.scalar(
        select(MonitoringSample).where(
            MonitoringSample.project_id == project_id,
            MonitoringSample.id == sample_id,
        )
    )
    if source is None:
        raise ProjectAccessError("monitoring_sample not found in this project")
    task = db.get(MonitoringTask, source.task_id)
    if task is None:
        raise ProjectAccessError("monitoring_task not found in this project")
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectAccessError("project not found")
    vocabulary = build_vocabulary(db, project_id, project=project)

    if not task.trace_id:
        task.trace_id = uuid.uuid4().hex
        db.flush()

    entry = db.get(AiEngineEntry, task.engine_entry_id)
    engine = db.get(AiEngine, entry.engine_id) if entry else None
    new_sample = _claim_sample(
        db,
        task,
        entry,
        engine,
        now=now or datetime.now(timezone.utc),
    )
    if new_sample is None:
        raise TaskRejectedError("样本已被其他请求占用，请稍后重试")
    new_sample.trace_id = source.trace_id or task.trace_id

    replay_adapter = adapter or build_entry_adapter(db, entry)
    used_stored_request = bool(
        source.request_payload is not None and hasattr(replay_adapter, "collect_with_request")
    )
    gateway = EngineGateway(
        replay_adapter,
        input_price_cny_per_million=(
            settings.deepseek_input_price_cny_per_million
            if engine is not None and engine.code == "deepseek"
            else None
        ),
        output_price_cny_per_million=(
            settings.deepseek_output_price_cny_per_million
            if engine is not None and engine.code == "deepseek"
            else None
        ),
    )
    try:
        payload = gateway.collect(
            task,
            trace_id=new_sample.trace_id,
            request_payload=source.request_payload if used_stored_request else None,
        )
    except CollectionFailure as failure:
        new_sample.request_payload = getattr(failure, "request_payload", None)
        new_sample.latency_ms = getattr(failure, "latency_ms", None)
        new_sample.gateway_version = GATEWAY_VERSION
        _mark_failure(new_sample, failure)
        db.flush()
        return {
            "sample_id": str(new_sample.id),
            "task_id": str(task.id),
            "trace_id": new_sample.trace_id,
            "status": new_sample.status.value,
            "failure_code": failure.failure_code.value,
            "failure_note": str(failure),
            "used_stored_request": used_stored_request,
        }
    except Exception as exc:
        failure = TransientCollectionFailure(str(exc), failure_code=FailureCode.OTHER)
        setattr(failure, "request_payload", getattr(exc, "request_payload", None))
        setattr(failure, "latency_ms", getattr(exc, "latency_ms", None))
        new_sample.request_payload = getattr(failure, "request_payload", None)
        new_sample.latency_ms = getattr(failure, "latency_ms", None)
        new_sample.gateway_version = GATEWAY_VERSION
        _mark_failure(new_sample, failure)
        db.flush()
        return {
            "sample_id": str(new_sample.id),
            "task_id": str(task.id),
            "trace_id": new_sample.trace_id,
            "status": new_sample.status.value,
            "failure_code": failure.failure_code.value,
            "failure_note": str(failure),
            "used_stored_request": used_stored_request,
        }

    result = apply_answer_payload(
        db,
        new_sample,
        payload,
        brand_terms=vocabulary.mention_terms,
        brand_domains=vocabulary.owned_domains,
        brand_identifiers=vocabulary.identifier_terms,
    )
    new_sample.status = ensure_sample_transition(
        SampleStatus.RUNNING,
        SampleStatus.HIT if result["brand_mentioned"] else SampleStatus.MISS,
    )
    new_sample.finished_at = datetime.now(timezone.utc)
    db.flush()
    return {
        "sample_id": str(new_sample.id),
        "task_id": str(task.id),
        "trace_id": new_sample.trace_id,
        "status": new_sample.status.value,
        "brand_mentioned": result["brand_mentioned"],
        "brand_identified": result["brand_identified"],
        "citation_count": result["citation_count"],
        "latency_ms": new_sample.latency_ms,
        "total_tokens": new_sample.total_tokens,
        "estimated_cost_cny": (
            float(new_sample.estimated_cost_cny)
            if new_sample.estimated_cost_cny is not None
            else None
        ),
        "used_stored_request": used_stored_request,
    }


def mark_task_failed(
    db: Session,
    *,
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    failure_code: FailureCode,
    note: str,
) -> None:
    task = db.scalar(
        select(MonitoringTask).where(
            MonitoringTask.project_id == project_id,
            MonitoringTask.id == task_id,
        )
    )
    if task is None:
        return
    task.status = ensure_task_transition(task.status, TaskStatus.FAILED)
    latest = db.scalar(
        select(MonitoringSample)
        .where(MonitoringSample.task_id == task.id)
        .order_by(MonitoringSample.attempt_no.desc())
        .limit(1)
    )
    if latest is not None and latest.status == SampleStatus.RUNNING:
        latest.status = SampleStatus.FAILED
        latest.failure_code = failure_code
        latest.failure_note = note
        latest.finished_at = datetime.now(timezone.utc)
    db.flush()


def run_pending_tasks(
    db: Session,
    *,
    project_id: uuid.UUID,
    round_id: uuid.UUID | None = None,
    adapter: AnswerAdapter | None = None,
    rate_limiter: EngineRateLimiter | None = None,
) -> dict[str, Any]:
    """CLI/轮次补跑：只处理 pending 任务，失败可重试异常不在本函数重试。"""
    filters = [
        MonitoringTask.project_id == project_id,
        MonitoringTask.status == TaskStatus.PENDING,
    ]
    if round_id is not None:
        filters.append(MonitoringTask.round_id == round_id)
    task_ids = db.scalars(select(MonitoringTask.id).where(*filters)).all()

    executed = 0
    failed = 0
    skipped = 0
    for task_id in task_ids:
        try:
            result = execute_task(
                db,
                project_id=project_id,
                task_id=task_id,
                adapter=adapter,
                rate_limiter=rate_limiter,
            )
            executed += 1
            if result.get("status") == "failed":
                failed += 1
            if result.get("skipped"):
                skipped += 1
        except CollectionFailure:
            failed += 1
    return {
        "project_id": str(project_id),
        "round_id": str(round_id) if round_id else None,
        "task_count": len(task_ids),
        "executed_count": executed,
        "failed_count": failed,
        "skipped_count": skipped,
    }
