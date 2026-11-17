"""监测自动采集链：按轮次生成任务、样本抢占、适配器调用与失败归档。

分工：
- `plan_round_tasks`：调度器可重复执行，按唯一键幂等建 pending 任务；不生成轮次；
- `schedule_active_rounds`：扫描 active 项目 + planning/running 轮次，建任务并为新建任务写 outbox；
- `execute_task`：Worker/CLI 执行单个任务，按样本 `(task_id, attempt_no)` 唯一约束抢占，
  真实适配器通过 `AnswerAdapter` 注入，未接适配器时落 `access_blocked`，不伪造 hit/miss；
  同一任务用 Postgres 事务级 advisory lock 串行化，重复投递只执行一次；
- `EngineRateLimiter`：每引擎每分钟限流，命中后由 Worker 直接落失败终态（不再重试）。
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
from app.core.credentials import read_credential_env
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
from app.services.citation_attribution import build_published_index
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
    if entry.protocol == EngineProtocol.WENXIN_SEARCH:
        from app.services.wenxin_search_adapter import build_wenxin_search_adapter

        return build_wenxin_search_adapter(
            db,
            credential_ref=entry.credential_ref,
            entry_url=entry.entry_url,
        )
    if entry.protocol == EngineProtocol.DOUBAO_SEARCH:
        from app.services.doubao_search_adapter import build_doubao_search_adapter

        return build_doubao_search_adapter(
            db,
            credential_ref=entry.credential_ref,
            model_name=entry.model_name,
            entry_url=entry.entry_url,
        )
    if entry.protocol == EngineProtocol.DEEPSEEK_SEARCH:
        from app.services.deepseek_search_adapter import build_deepseek_search_adapter

        return build_deepseek_search_adapter(
            db,
            credential_ref=entry.credential_ref,
            entry_url=entry.entry_url,
        )
    if entry.protocol == EngineProtocol.DEEPSEEK_WEB_SEARCH:
        from app.services.deepseek_web_search_adapter import (
            build_deepseek_web_search_adapter,
        )

        return build_deepseek_web_search_adapter(
            db,
            credential_ref=entry.credential_ref,
            model_name=entry.model_name,
            entry_url=entry.entry_url,
        )
    if entry.protocol != EngineProtocol.OPENAI_COMPATIBLE:
        return UnconfiguredAdapter()
    if not entry.entry_url:
        raise AccessBlockedFailure("openai_compatible 入口未配置 entry_url")
    if not entry.model_name:
        raise AccessBlockedFailure("openai_compatible 入口未配置 model_name")

    api_key = ""
    if entry.credential_ref:
        api_key = read_credential_env(entry.credential_ref)
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

    def _is_websearch(self, engine_code: str) -> bool:
        return self._explicit_limit is None and "websearch" in engine_code

    def _limit_for(self, engine_code: str) -> int:
        """网页端采集（浏览器登录态）单独取更保守的上限，避免触发平台风控。"""
        if self._is_websearch(engine_code):
            return max(1, int(settings.monitoring_websearch_rate_limit_per_minute))
        return self.limit

    def _redis(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        return self._client

    def trip_cooldown(self, engine_code: str) -> None:
        """网页端被判限流后整引擎冷却一段时间，期间不再发起任何调用。"""
        if not self._is_websearch(engine_code):
            return
        minutes = max(1, int(settings.monitoring_websearch_cooldown_minutes))
        try:
            self._redis().set(
                f"geo:monitoring:cooldown:{engine_code}",
                "1",
                ex=minutes * 60,
            )
            logger.warning(
                "websearch engine cooling down",
                extra={"fields": {"engine_code": engine_code, "minutes": minutes}},
            )
        except redis.RedisError:
            logger.warning(
                "monitoring cooldown unavailable",
                extra={"fields": {"engine_code": engine_code}},
            )

    def allow(self, engine_code: str, *, now: datetime | None = None) -> bool:
        moment = now or datetime.now(timezone.utc)
        key = f"geo:monitoring:rate:{engine_code}:{int(moment.timestamp() // 60)}"
        limit = self._limit_for(engine_code)
        client = self._redis()
        try:
            if self._is_websearch(engine_code):
                if client.exists(f"geo:monitoring:cooldown:{engine_code}"):
                    return False
            count = int(client.incr(key))
            if count == 1:
                client.expire(key, 90)
            if count > limit:
                return False
            # 日额度只统计「分钟窗口已放行」的请求：被分钟限流挡掉的调度不能吃额度，
            # 否则一批任务在几十秒内触发，当天额度会被瞬间扣光。
            if self._is_websearch(engine_code):
                daily_key = f"geo:monitoring:daily:{engine_code}:{moment.strftime('%Y%m%d')}"
                daily = int(client.incr(daily_key))
                if daily == 1:
                    client.expire(daily_key, 172800)
                if daily > max(1, int(settings.monitoring_websearch_daily_cap)):
                    return False
            return True
        except redis.RedisError:
            logger.warning(
                "monitoring rate limit unavailable; allow request",
                extra={"fields": {"engine_code": engine_code}},
            )
            return True


def _lock_round_quota(db: Session, *, round_id: uuid.UUID, engine_id: uuid.UUID) -> None:
    """串行化「同一轮次 + 同一引擎」的单轮配额判断。

    配额是 check-then-act：多个 worker 同时看到 `used < cap` 会一起放行。这里用
    事务级 advisory lock 把同一轮同一引擎的计数与落库串起来，锁随事务结束释放。
    """
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return
    db.execute(
        select(
            func.pg_advisory_xact_lock(
                func.hashtext(f"geo:monitoring:round:{round_id}:{engine_id}")
            )
        )
    )


def _websearch_round_cap_reached(
    db: Session,
    *,
    round_id: uuid.UUID,
    engine: AiEngine | None,
    current_task_id: uuid.UUID,
) -> bool:
    """单轮网页端调用上限：同一轮次同一引擎最多跑 N 条，超出直接拒采。"""
    if engine is None or "websearch" not in engine.code:
        return False
    cap = max(1, int(settings.monitoring_websearch_round_cap))
    _lock_round_quota(db, round_id=round_id, engine_id=engine.id)
    entry_ids = db.scalars(
        select(AiEngineEntry.id).where(AiEngineEntry.engine_id == engine.id)
    ).all()
    if not entry_ids:
        return False
    # 只统计真正采集成功的任务：适配器失败/超时/限流的任务不占本轮额度，
    # 否则一轮里连续两次失败就会吃掉 40% 配额。
    used = db.scalar(
        select(func.count())
        .select_from(MonitoringTask)
        .where(
            MonitoringTask.round_id == round_id,
            MonitoringTask.engine_entry_id.in_(entry_ids),
            MonitoringTask.id != current_task_id,
            MonitoringTask.status == TaskStatus.DONE,
        )
    ) or 0
    return used >= cap


def _claim_task_execution(db: Session, task_id: uuid.UUID) -> bool:
    """串行化同一任务的执行：Postgres 事务级 advisory lock。

    Celery 开启 `acks_late`，worker 崩溃或 outbox 重投递时，同一条任务可能被两个
    worker 同时执行。没抢到锁的一方直接跳过，避免真实调用两次（token 重复计费、
    样本口径翻倍）；锁随事务结束自动释放，不占业务字段。
    """
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        # 非 Postgres（例如本地极简验证库）没有 advisory lock，退化为不锁。
        return True
    return bool(
        db.scalar(
            select(
                func.pg_try_advisory_xact_lock(
                    func.hashtext(f"geo:monitoring:task:{task_id}")
                )
            )
        )
    )


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
    published_index: dict | None = None,
    retry_on_failure: bool = True,
) -> dict[str, Any]:
    """执行单个任务；成功/终态失败返回落库结果。

    可重试失败默认抛 CollectionFailure，交给 Worker 重试；批量补跑传
    ``retry_on_failure=False``，让失败样本随 savepoint 一起提交，否则回滚会把
    failure_code / failure_note 一并丢掉，只剩一个没有原因的 failed 任务。
    """
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
    if not _claim_task_execution(db, task.id):
        return {
            "task_id": str(task.id),
            "status": task.status.value,
            "skipped": "task is executing in another worker",
        }
    # 品牌口径统一从项目品牌实体取，未配置时回退到项目名/项目 code（历史口径不变）。
    vocabulary = build_vocabulary(db, project_id, project=project)

    if task.status == TaskStatus.PENDING:
        task.status = ensure_task_transition(task.status, TaskStatus.RUNNING)
        db.flush()

    # 老任务没有 trace_id 时补一个，样本/引用都沿用它，保证排障可串。
    if not task.trace_id:
        task.trace_id = uuid.uuid4().hex
        db.flush()

    entry = db.get(AiEngineEntry, task.engine_entry_id)
    engine = db.get(AiEngine, entry.engine_id) if entry else None
    if _websearch_round_cap_reached(
        db, round_id=task.round_id, engine=engine, current_task_id=task.id
    ):
        # 单轮网页端配额用完：不调用引擎，落一条失败样本说明原因，任务进失败终态。
        # 配额判断已由 `_lock_round_quota` 串行化，这里只负责留痕。
        task.status = ensure_task_transition(task.status, TaskStatus.FAILED)
        db.flush()
        quota_now = now or datetime.now(timezone.utc)
        quota_note = f"本轮网页端采集已达 {settings.monitoring_websearch_round_cap} 条上限"
        sample = _claim_sample(db, task, entry, engine, now=quota_now)
        if sample is not None:
            sample.status = SampleStatus.FAILED
            # 现有库的 failure_code CHECK 约束不含新枚举值；用 other + note 留痕，
            # 不为了一个展示字段引入迁移。
            sample.failure_code = FailureCode.OTHER
            sample.failure_note = quota_note
            sample.finished_at = quota_now
            db.flush()
        logger.warning(
            "websearch round quota reached",
            extra={
                "fields": {
                    "task_id": str(task.id),
                    "round_id": str(task.round_id),
                    "engine_code": engine.code if engine is not None else None,
                    "cap": settings.monitoring_websearch_round_cap,
                }
            },
        )
        return {
            "task_id": str(task.id),
            "status": TaskStatus.FAILED.value,
            "failure_code": FailureCode.OTHER.value,
            "note": quota_note,
        }
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
        if (
            failure.failure_code == FailureCode.RATE_LIMITED
            and engine is not None
            and rate_limiter is not None
        ):
            # 网页端一旦被判限流，整引擎进入冷却，后续任务不再连续试探
            rate_limiter.trip_cooldown(engine.code)
        if not failure.retryable or not retry_on_failure:
            task.status = ensure_task_transition(task.status, TaskStatus.FAILED)
        db.flush()
        if failure.retryable and retry_on_failure:
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
        published_index=published_index,
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
    published_index: dict | None = None,
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
        published_index=published_index,
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
    if task.status == TaskStatus.PENDING:
        # 调用方可能已经把 pending→running 回滚掉（例如限流分支先 rollback 再落失败），
        # 这里补一次「已尝试」的中间态，避免 pending→failed 被状态机拒绝后任务卡在 pending。
        task.status = ensure_task_transition(task.status, TaskStatus.RUNNING)
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
    # 整批任务共用一份发布回执索引：同一项目的回执在补跑期间不会变化
    published_index = build_published_index(db, project_id) if task_ids else None
    for task_id in task_ids:
        savepoint = db.begin_nested()
        try:
            result = execute_task(
                db,
                project_id=project_id,
                task_id=task_id,
                adapter=adapter,
                rate_limiter=rate_limiter,
                published_index=published_index,
                retry_on_failure=False,
            )
            savepoint.commit()
            executed += 1
            if result.get("status") == "failed":
                failed += 1
            if result.get("skipped"):
                skipped += 1
        except CollectionFailure as failure:
            # 只回滚本任务的半写状态，不影响前面已成功的任务；批量补跑不重试，
            # 可重试失败也直接落终态，避免任务停在 running 再也不会被 pending 扫描拾起。
            savepoint.rollback()
            failed += 1
            mark_task_failed(
                db,
                project_id=project_id,
                task_id=task_id,
                failure_code=failure.failure_code,
                note=str(failure),
            )
        except Exception:
            savepoint.rollback()
            raise
    return {
        "project_id": str(project_id),
        "round_id": str(round_id) if round_id else None,
        "task_count": len(task_ids),
        "executed_count": executed,
        "failed_count": failed,
        "skipped_count": skipped,
    }
