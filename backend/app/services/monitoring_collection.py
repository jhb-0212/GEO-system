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
    FailureCode,
    ProjectStatus,
    QuestionStatus,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    TaskStatus,
)
from app.services.monitoring_extraction import (
    AnswerPayload,
    apply_answer_payload,
)
from app.services.outbox import emit_event

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


class EngineRateLimiter:
    """每引擎每分钟滑动窗口限流；Redis 故障时放行并告警，不阻断采集。"""

    def __init__(
        self,
        client: redis.Redis | None = None,
        *,
        limit_per_minute: int | None = None,
    ) -> None:
        self._client = client
        self.limit = max(1, int(limit_per_minute or settings.monitoring_engine_rate_limit_per_minute))

    def _redis(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        return self._client

    def allow(self, engine_code: str, *, now: datetime | None = None) -> bool:
        moment = now or datetime.now(timezone.utc)
        key = f"geo:monitoring:rate:{engine_code}:{int(moment.timestamp() // 60)}"
        try:
            count = int(self._redis().incr(key))
            if count == 1:
                self._redis().expire(key, 90)
            return count <= self.limit
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
    sample.status = SampleStatus.FAILED
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

    if task.status == TaskStatus.PENDING:
        task.status = TaskStatus.RUNNING
        db.flush()
    elif task.status != TaskStatus.RUNNING:
        raise TaskRejectedError(f"任务状态 {task.status} 不可执行")

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

    adapter = adapter or UnconfiguredAdapter()
    try:
        payload = adapter.collect(task)
    except CollectionFailure as failure:
        _mark_failure(sample, failure)
        if not failure.retryable:
            task.status = TaskStatus.FAILED
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
        _mark_failure(sample, failure)
        db.flush()
        raise failure from exc

    result = apply_answer_payload(
        db,
        sample,
        payload,
        brand_terms=[term for term in (project.name, project.code) if term],
    )
    sample.status = SampleStatus.HIT if result["brand_mentioned"] else SampleStatus.MISS
    sample.finished_at = datetime.now(timezone.utc)
    task.status = TaskStatus.DONE
    db.flush()
    return {
        "task_id": str(task.id),
        "sample_id": str(sample.id),
        "status": sample.status.value,
        "brand_mentioned": result["brand_mentioned"],
        "citation_count": result["citation_count"],
        "competitor_mention_count": result["competitor_mention_count"],
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
    task.status = TaskStatus.FAILED
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
