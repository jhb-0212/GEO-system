"""监测自动采集链：按轮次生成任务、样本抢占、适配器调用与失败归档。

分工：
- `plan_round_tasks`：调度器可重复执行，按唯一键幂等建 pending 任务；不生成轮次；
- `schedule_active_rounds`：扫描 active 项目 + planning/running 轮次，建任务并为新建任务写 outbox；
- `execute_task`：Worker/CLI 执行单个任务，按样本 `(task_id, attempt_no)` 唯一约束抢占，
  真实适配器通过 `AnswerAdapter` 注入，未接适配器时落 `access_blocked`，不伪造 hit/miss；
  执行权以数据库原子条件更新为唯一事实源（见 `_claim_task_execution`），
  租约有效期内的重复投递、终态与 UNCERTAIN 任务一律跳过，不重复调用外部平台；
- `EngineRateLimiter`：每引擎每分钟限流，命中后由 Worker 直接落失败终态（不再重试）。
"""

from __future__ import annotations

import logging
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import redis
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.secrets_box import decrypt_secret
from app.core.errors import ProjectAccessError, TaskRejectedError
from app.services.state_machine import ensure_attempt_transition
from app.models import (
    AiEngine,
    AiEngineEntry,
    MonitoringExecutionAttempt,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Project,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    AttemptStatus,
    EngineEntryType,
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
from app.services.citation_attribution import build_domain_channel_index, build_published_index
from app.services.engine_gateway import GATEWAY_VERSION, EngineGateway
from app.services.engine_credentials import resolve_entry_secret
from app.services.measurement_snapshot import snapshot_rules_version, vocabulary_from_snapshot
from app.services.monitoring_extraction import (
    AnswerPayload,
    CitationInput,
    CompetitorMentionInput,
    apply_answer_payload,
    parse_raw_response,
)
from app.services.outbox import emit_event
from app.services.state_machine import ensure_sample_transition, ensure_task_transition

logger = logging.getLogger(__name__)

# INCR 与 EXPIRE 必须原子：先 INCR 后 EXPIRE 中途失败会留下没有 TTL 的计数键。
_LIMIT_LUA = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
return count
"""


def _worker_identity() -> str:
    """当前执行实例标识：写进任务租约，回收时据此判断归属。"""
    return f"{socket.gethostname()}:{os.getpid()}"[:64]


def _bump_counter(client, key: str, ttl_seconds: int) -> int:
    """原子自增并设置 TTL；不支持 EVAL 的客户端退化为 INCR+EXPIRE。"""
    if hasattr(client, "eval"):
        return int(client.eval(_LIMIT_LUA, 1, key, ttl_seconds))
    count = int(client.incr(key))
    if count == 1:
        client.expire(key, ttl_seconds)
    return count


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

    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason

    def collect(self, task: MonitoringTask) -> AnswerPayload:
        detail = self.reason or "引擎适配器未配置"
        raise AccessBlockedFailure(f"{detail}；未发起真实请求")


class FakeEngineAdapter:
    """仅开发/测试：给 API 入口返回确定性答案，不发起任何外部请求。

    生成内容固定标注 fake_engine，样本 request_payload 可追溯；生产环境
    由配置校验直接拒绝开启。竞品提及走结构化字段，不靠正文猜测。
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.last_request_payload: dict[str, Any] | None = None

    def collect(self, task: MonitoringTask) -> AnswerPayload:
        from app.models import BrandProfile, Competitor, QuestionVersion

        self.last_request_payload = {"fake_engine": True, "task_id": str(task.id)}
        brand = self.db.scalar(
            select(BrandProfile).where(
                BrandProfile.project_id == task.project_id,
                BrandProfile.is_active.is_(True),
            )
        )
        competitor = self.db.scalar(
            select(Competitor)
            .where(Competitor.project_id == task.project_id, Competitor.is_active.is_(True))
            .order_by(Competitor.created_at)
        )
        version = self.db.get(QuestionVersion, task.question_version_id)
        question = version.text if version is not None else "演练问题"
        brand_name = brand.canonical_name if brand is not None else None
        parts = [f"演练回答（假引擎）：围绕「{question}」，"]
        if brand_name:
            parts.append(f"{brand_name} 的相关信息可参考其官方页面。")
        else:
            parts.append("暂未配置品牌档案，本回答仅用于验证采集链路。")
        if competitor is not None:
            parts.append(f"同领域也可关注 {competitor.name}。")
        citations: list[CitationInput] = []
        domain = None
        if brand is not None and brand.owned_domains:
            domain = str(brand.owned_domains[0]).replace("https://", "").replace("http://", "").strip("/")
        domain = domain or "example.com"
        citations.append(CitationInput(url=f"https://{domain}/fake-engine/{task.id}"))
        return AnswerPayload(
            text="".join(parts),
            citations=citations,
            competitor_mentions=(
                [
                    CompetitorMentionInput(
                        name=competitor.name,
                        evidence_text=f"同领域也可关注 {competitor.name}",
                    )
                ]
                if competitor is not None
                else []
            ),
            raw_response={"fake_engine": True, "task_id": str(task.id)},
            request_payload={"fake_engine": True, "task_id": str(task.id)},
            gateway_version="fake_engine_v1",
        )


def build_entry_adapter(db: Session, entry: AiEngineEntry | None) -> AnswerAdapter:
    """按入口协议选适配器；未接协议继续明确失败，不伪造答案。"""
    if settings.monitoring_fake_engine_enabled:
        return FakeEngineAdapter(db)
    if entry is None:
        return UnconfiguredAdapter()
    from app.services.engine_url_policy import validate_engine_url

    try:
        validate_engine_url(entry.entry_url, entry.protocol)
    except ValueError as exc:
        return UnconfiguredAdapter(reason=str(exc))
    # 所有入口接真实适配器前都先过地址策略。新增协议（含把 custom 接到实现）时，
    # 必须同时把它的 host 收进 OFFICIAL_PROVIDER_HOSTS / ENGINE_ALLOWED_HOSTS，
    # 不能指望这一行的通用校验替你收口域名。
    if entry.protocol == EngineProtocol.YUANBAO_SEARCH:
        from app.services.yuanbao_search_adapter import build_yuanbao_adapter

        return build_yuanbao_adapter(
            db,
            credential_ref=entry.credential_ref,
            entry_url=entry.entry_url,
            stored_secret=decrypt_secret(entry.encrypted_secret),
            stored_secret_secondary=decrypt_secret(entry.encrypted_secret_secondary),
        )
    if entry.protocol == EngineProtocol.WENXIN_SEARCH:
        from app.services.wenxin_search_adapter import build_wenxin_search_adapter

        return build_wenxin_search_adapter(
            db,
            credential_ref=entry.credential_ref,
            entry_url=entry.entry_url,
            stored_secret=decrypt_secret(entry.encrypted_secret),
        )
    if entry.protocol == EngineProtocol.DOUBAO_SEARCH:
        from app.services.doubao_search_adapter import build_doubao_search_adapter

        return build_doubao_search_adapter(
            db,
            credential_ref=entry.credential_ref,
            model_name=entry.model_name,
            entry_url=entry.entry_url,
            stored_secret=decrypt_secret(entry.encrypted_secret),
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
            stored_secret=decrypt_secret(entry.encrypted_secret),
        )
    if entry.protocol != EngineProtocol.OPENAI_COMPATIBLE:
        return UnconfiguredAdapter()
    if not entry.entry_url:
        raise AccessBlockedFailure("openai_compatible 入口未配置 entry_url")
    if not entry.model_name:
        raise AccessBlockedFailure("openai_compatible 入口未配置 model_name")

    # Kimi 的联网搜索走 Responses 的 web_search 工具，响应结构与 Chat
    # Completions 不同；仅在入口显式打开 supports_search 时切过去。
    from app.services.engine_web_search import (
        is_kimi_web_search_entry,
        is_metaso_web_search_entry,
        is_qianfan_model_web_search_entry,
        is_qihu360_ai_search_entry,
        is_qwen_web_search_entry,
        is_spark_web_search_entry,
        is_zhipu_web_search_entry,
    )

    if is_kimi_web_search_entry(entry):
        from app.services.kimi_web_search_adapter import build_kimi_web_search_adapter

        return build_kimi_web_search_adapter(
            db,
            credential_ref=entry.credential_ref,
            model_name=entry.model_name,
            entry_url=entry.entry_url,
            stored_secret=decrypt_secret(entry.encrypted_secret),
        )

    # 千问 Chat Completions 的 enable_search 不回传 search_info，引用为 0；
    # 改走同一 Key 的 Responses web_search，从 action.sources 落引用。
    if is_qwen_web_search_entry(entry):
        from app.services.qwen_web_search_adapter import build_qwen_web_search_adapter

        return build_qwen_web_search_adapter(
            db,
            credential_ref=entry.credential_ref,
            model_name=entry.model_name,
            entry_url=entry.entry_url,
            stored_secret=decrypt_secret(entry.encrypted_secret),
        )

    # 360 智脑 AI 搜索是独立 endpoint，不是 Chat Completions；不能走通用适配器。
    if is_qihu360_ai_search_entry(entry):
        from app.services.qihu360_search_adapter import build_qihu360_search_adapter

        return build_qihu360_search_adapter(
            db,
            credential_ref=entry.credential_ref,
            model_name=entry.model_name,
            entry_url=entry.entry_url,
            stored_secret=decrypt_secret(entry.encrypted_secret),
        )

    # 智谱不绑定模型：独立 Web Search API 取来源，再用入口配置的模型回答。
    # 这样 FlashX / GLM-5.3 / 免费模型都走同一条链路，入口只改 model_name。
    if is_zhipu_web_search_entry(entry):
        from app.services.zhipu_search_adapter import ZhipuModelSearchAdapter

        api_key = resolve_entry_secret(entry)
        if not api_key and (entry.credential_ref or entry.encrypted_secret):
            raise AccessBlockedFailure(
                f"未配置密钥（系统内填写或环境变量 {entry.credential_ref or '—'}），入口无法调用"
            )
        return ZhipuModelSearchAdapter(
            db,
            base_url=entry.entry_url,
            model=entry.model_name,
            api_key=api_key,
        )

    api_key = resolve_entry_secret(entry)
    if not api_key and (entry.credential_ref or entry.encrypted_secret):
        raise AccessBlockedFailure(
            f"未配置密钥（系统内填写或环境变量 {entry.credential_ref or '—'}），入口无法调用"
        )

    web_search_mode: str | None = None
    if is_qianfan_model_web_search_entry(entry):
        web_search_mode = "qianfan"
    elif is_metaso_web_search_entry(entry):
        web_search_mode = "metaso"
    elif is_spark_web_search_entry(entry):
        web_search_mode = "spark"

    # 延迟导入，避免 monitoring_collection ←→ 适配器模块循环依赖。
    from app.services.openai_compatible_adapter import OpenAICompatibleAdapter

    return OpenAICompatibleAdapter(
        db,
        base_url=entry.entry_url,
        model=entry.model_name,
        api_key=api_key,
        web_search_mode=web_search_mode,
        enable_web_search=web_search_mode == "qianfan",
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
        websearch = self._is_websearch(engine_code)
        try:
            if websearch and client.exists(f"geo:monitoring:cooldown:{engine_code}"):
                return False
            count = _bump_counter(client, key, 90)
            if count > limit:
                return False
            # 日额度只统计「分钟窗口已放行」的请求：被分钟限流挡掉的调度不能吃额度，
            # 否则一批任务在几十秒内触发，当天额度会被瞬间扣光。
            if websearch:
                daily_key = f"geo:monitoring:daily:{engine_code}:{moment.strftime('%Y%m%d')}"
                daily = _bump_counter(client, daily_key, 172800)
                if daily > max(1, int(settings.monitoring_websearch_daily_cap)):
                    return False
            return True
        except redis.RedisError:
            if websearch:
                # 网页端采集直接对上游平台发起请求，限流器失效时不能无保护放行
                logger.error(
                    "monitoring rate limit unavailable; block websearch request",
                    extra={"fields": {"engine_code": engine_code}},
                )
                return False
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


def _claim_task_execution(
    db: Session,
    task: MonitoringTask,
    *,
    worker_id: str | None = None,
    now: datetime | None = None,
) -> bool:
    """原子领取执行权：一条条件 UPDATE 完成“状态可领取 + 租约未持有”的抢占。

    Celery 开启 `acks_late`，worker 崩溃或 outbox 重投递时，同一条任务可能被两个
    worker 同时执行，也可能被重复投递。这里不再依赖事务级 advisory lock（提交后
    即失效），改以 UPDATE 行锁为唯一事实源：

    - 满足条件的 UPDATE 影响 1 行才获得执行权；行锁持有到本事务结束；
    - 并发领取者会等第一个事务提交后按 WHERE 重新评估，租约未过期则 0 行跳过；
    - 租约有效期内的重复消息、终态（DONE/FAILED/CANCELLED）与 UNCERTAIN 任务
      都在 WHERE 条件处被挡掉，不会重复创建样本或重复计费。

    领取条件：
    - PENDING：待执行，直接领取并置 RUNNING；
    - RUNNING 且（租约为空或已过期）：旧执行权已失效，可重新领取；
    - 其他状态一律不可自动领取。

    ``worker_id`` 为空时不写租约（批量补跑/测试的单事务语义），只做状态抢占。
    """
    moment = now or datetime.now(timezone.utc)
    lease_expires_at = None
    if worker_id is not None:
        lease_expires_at = moment + timedelta(
            seconds=settings.monitoring_task_lease_seconds
        )

    status_claimable = or_(
        MonitoringTask.status == TaskStatus.PENDING,
        and_(
            MonitoringTask.status == TaskStatus.RUNNING,
            or_(
                MonitoringTask.lease_expires_at.is_(None),
                MonitoringTask.lease_expires_at < moment,
            ),
        ),
    )
    result = db.execute(
        update(MonitoringTask)
        .where(MonitoringTask.id == task.id, status_claimable)
        .values(
            status=TaskStatus.RUNNING,
            lease_owner=worker_id,
            lease_expires_at=lease_expires_at,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        return False
    # UPDATE 不经过 ORM 会话，手动同步对象状态，避免后续 flush 用旧值覆盖。
    task.status = TaskStatus.RUNNING
    task.lease_owner = worker_id
    task.lease_expires_at = lease_expires_at
    return True


def _active_engine_entries(
    db: Session, *, require_search: bool
) -> list[tuple[AiEngine, AiEngineEntry]]:
    stmt = select(AiEngine, AiEngineEntry).join(
        AiEngineEntry, AiEngineEntry.engine_id == AiEngine.id
    ).where(AiEngine.is_active.is_(True), AiEngineEntry.is_active.is_(True))
    if require_search:
        stmt = stmt.where(AiEngineEntry.supports_search.is_(True))
    rows = db.execute(
        stmt.order_by(AiEngine.code, AiEngineEntry.created_at, AiEngineEntry.id)
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
    if round_row.status not in (RoundStatus.PLANNING, RoundStatus.RUNNING):
        raise TaskRejectedError("本轮次已结束，不能补建任务；请新建轮次后再抽")
    # 人工入口轮次不能被调度器扩大成自动基线：app_search/web_user/app_user
    # 都是人工采样，一旦存在就跳过自动补任务和 outbox 派发。
    manual_task_count = int(
        db.scalar(
            select(func.count())
            .select_from(MonitoringTask)
            .join(AiEngineEntry, AiEngineEntry.id == MonitoringTask.engine_entry_id)
            .where(
                MonitoringTask.round_id == round_id,
                AiEngineEntry.entry_type.in_(
                    (
                        EngineEntryType.APP_SEARCH,
                        EngineEntryType.WEB_USER,
                        EngineEntryType.APP_USER,
                    )
                ),
            )
        )
        or 0
    )
    if manual_task_count:
        return {
            "project_id": str(project_id),
            "round_id": str(round_id),
            "question_count": 0,
            "engine_count": 0,
            "created_task_ids": [],
            "existing_task_count": manual_task_count,
            "skipped_reason": "manual_round",
        }

    questions = _active_question_versions(db, project_id)
    engines = _active_engine_entries(
        db, require_search=sampling_mode == SamplingMode.SEARCH_ON
    )
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
        conversation_id=uuid.uuid4().hex,
        conversation_mode=(
            "fresh"
            if entry is not None and entry.entry_type == EngineEntryType.WEB_USER
            else "stateless"
        ),
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


def _observation_status(sample: MonitoringSample, result: dict[str, Any]) -> SampleStatus:
    """成功请求后的样本状态：空正文且无引用记为「无答案面」，不得冒充 miss。

    - 有正文：按品牌是否被提及判 hit / miss；
    - 无正文但有引用：仍是一次可分析的结果（检索可见性），按提及判 hit / miss；
    - 无正文且无引用：入口可用但没有答案界面，独立状态，不进入有效分母。
    """
    has_text = bool((sample.raw_answer or "").strip())
    if not has_text and int(result.get("citation_count") or 0) == 0:
        return SampleStatus.NO_ANSWER_SURFACE
    return SampleStatus.HIT if result["brand_mentioned"] else SampleStatus.MISS


def recover_expired_leases(
    db: Session,
    *,
    now: datetime | None = None,
    limit: int = 100,
) -> dict[str, int]:
    """回收租约过期的 running 任务：请求已发出的判 uncertain，未发出的退回 pending。"""
    moment = now or datetime.now(timezone.utc)
    tasks = db.scalars(
        select(MonitoringTask)
        .where(
            MonitoringTask.status == TaskStatus.RUNNING,
            MonitoringTask.lease_expires_at.is_not(None),
            MonitoringTask.lease_expires_at < moment,
        )
        .order_by(MonitoringTask.lease_expires_at)
        .limit(limit)
    ).all()
    recovered = 0
    uncertain = 0
    for task in tasks:
        attempt = db.scalar(
            select(MonitoringExecutionAttempt)
            .where(MonitoringExecutionAttempt.task_id == task.id)
            .order_by(MonitoringExecutionAttempt.attempt_no.desc())
            .limit(1)
        )
        sample = db.scalar(
            select(MonitoringSample)
            .where(MonitoringSample.task_id == task.id)
            .order_by(MonitoringSample.attempt_no.desc())
            .limit(1)
        )
        dispatched = attempt is not None and attempt.status in (
            AttemptStatus.DISPATCHING,
            AttemptStatus.SUCCEEDED,
        )
        note = "执行租约过期"
        if dispatched:
            # 外部请求可能已经完成并计费：不能自动重发，只能标记结果不确定
            task.status = ensure_task_transition(task.status, TaskStatus.UNCERTAIN)
            if attempt is not None:
                attempt.status = ensure_attempt_transition(attempt.status, AttemptStatus.UNCERTAIN)
                attempt.finished_at = moment
                attempt.note = note
            if sample is not None and sample.status == SampleStatus.RUNNING:
                sample.status = ensure_sample_transition(sample.status, SampleStatus.FAILED)
                sample.failure_code = FailureCode.OTHER
                sample.failure_note = f"{note}：请求已发出，结果未知，需人工核实"
                sample.finished_at = moment
            uncertain += 1
        else:
            task.status = ensure_task_transition(task.status, TaskStatus.PENDING)
            if attempt is not None:
                attempt.status = ensure_attempt_transition(attempt.status, AttemptStatus.LEASE_EXPIRED)
                attempt.finished_at = moment
                attempt.note = note
            if sample is not None and sample.status == SampleStatus.RUNNING:
                sample.status = ensure_sample_transition(sample.status, SampleStatus.FAILED)
                sample.failure_code = FailureCode.OTHER
                sample.failure_note = f"{note}：未发出外部请求，任务已重排"
                sample.finished_at = moment
            recovered += 1
        task.lease_owner = None
        task.lease_expires_at = None
        db.flush()
    db.commit()
    if tasks:
        logger.warning(
            "expired monitoring leases recovered",
            extra={
                "fields": {
                    "count": len(tasks),
                    "requeued": recovered,
                    "uncertain": uncertain,
                }
            },
        )
    return {"scanned": len(tasks), "requeued": recovered, "uncertain": uncertain}


def execute_task(
    db: Session,
    *,
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    adapter: AnswerAdapter | None = None,
    rate_limiter: EngineRateLimiter | None = None,
    now: datetime | None = None,
    published_index: dict | None = None,
    domain_channel_index: dict | None = None,
    retry_on_failure: bool = True,
    worker_id: str | None = None,
) -> dict[str, Any]:
    """执行单个任务；成功/终态失败返回落库结果。

    ``worker_id`` 由 Worker 传入时启用租约模式：原子领取并提交（行锁与
    写事务随领取提交结束）后才发起外部请求，执行尝试单独留痕；未传时保持
    旧的单事务语义，供批量补跑/测试使用。

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
    if task.status == TaskStatus.UNCERTAIN:
        # 请求可能已发出且结果不明（租约回收判定），禁止自动重发；人工核实后
        # 转回 PENDING 才能重新进入执行流。
        return {
            "task_id": str(task.id),
            "status": task.status.value,
            "skipped": "task awaiting manual review",
        }
    if not _claim_task_execution(db, task, worker_id=worker_id, now=now):
        return {
            "task_id": str(task.id),
            "status": task.status.value,
            "skipped": "task is executing in another worker",
        }
    # 品牌口径优先读轮次快照（同一轮内口径固定）；旧轮次没有快照时才回退到
    # 当前 BrandProfile，保证历史轮次仍可补跑。
    round_row = db.get(MonitoringRound, task.round_id)
    snapshot_vocabulary = vocabulary_from_snapshot(
        round_row.analysis_config_snapshot if round_row is not None else None
    )
    vocabulary = snapshot_vocabulary or build_vocabulary(db, project_id, project=project)

    # 领取成功后任务已置 RUNNING（见 _claim_task_execution）；旧代码的
    # PENDING→RUNNING 显式迁移已由领取条件白名单承接，不再重复执行。

    # 老任务没有 trace_id 时补一个，样本/引用都沿用它，保证排障可串。
    if not task.trace_id:
        task.trace_id = uuid.uuid4().hex
        db.flush()

    entry = db.get(AiEngineEntry, task.engine_entry_id)
    engine = db.get(AiEngine, entry.engine_id) if entry else None
    if task.sampling_mode == SamplingMode.SEARCH_ON and (
        entry is None or not entry.supports_search
    ):
        # 旧任务/人工改动可能绕过创建时的入口过滤；执行前再硬校验一次，
        # 不让无联网能力的入口伪造“搜索可见性”样本。
        note = "入口未开启联网搜索能力，不能执行 search_on 任务"
        task.status = ensure_task_transition(task.status, TaskStatus.FAILED)
        failed_at = now or datetime.now(timezone.utc)
        sample = _claim_sample(db, task, entry, engine, now=failed_at)
        if sample is not None:
            sample.status = SampleStatus.FAILED
            sample.failure_code = FailureCode.OTHER
            sample.failure_note = note
            sample.finished_at = failed_at
        db.flush()
        return {
            "task_id": str(task.id),
            "status": TaskStatus.FAILED.value,
            "failure_code": FailureCode.OTHER.value,
            "note": note,
        }
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

    attempt: MonitoringExecutionAttempt | None = None
    if worker_id:
        claimed_at = now or datetime.now(timezone.utc)
        # 租约已由 _claim_task_execution 原子写入，这里只创建执行尝试留痕。
        attempt = MonitoringExecutionAttempt(
            project_id=task.project_id,
            task_id=task.id,
            attempt_no=sample.attempt_no,
            worker_id=worker_id,
            status=AttemptStatus.DISPATCHING,
            lease_expires_at=task.lease_expires_at,
            started_at=claimed_at,
        )
        db.add(attempt)
        db.flush()
        # 阶段 A 结束：提交领取状态，释放事务级 advisory lock 与数据库连接；
        # 外部请求期间不再持有写事务，崩溃后由租约回收而不是靠锁兜底。
        db.commit()

    if rate_limiter is not None and engine is not None:
        if not rate_limiter.allow(engine.code, now=now):
            note = f"引擎 {engine.code} 超过每分钟调用上限"
            sample.status = ensure_sample_transition(sample.status, SampleStatus.FAILED)
            sample.failure_code = FailureCode.RATE_LIMITED
            sample.failure_note = note
            sample.finished_at = datetime.now(timezone.utc)
            if attempt is not None:
                attempt.status = ensure_attempt_transition(attempt.status, AttemptStatus.RATE_LIMITED)
                attempt.finished_at = datetime.now(timezone.utc)
                attempt.note = note
                task.lease_owner = None
                task.lease_expires_at = None
            db.flush()
            raise RateLimitedFailure(note)

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
        if attempt is not None:
            attempt.status = ensure_attempt_transition(attempt.status, AttemptStatus.FAILED)
            attempt.failure_code = failure.failure_code
            attempt.finished_at = datetime.now(timezone.utc)
            attempt.note = str(failure)
        if not failure.retryable or not retry_on_failure:
            task.status = ensure_task_transition(task.status, TaskStatus.FAILED)
        if not (failure.retryable and retry_on_failure):
            task.lease_owner = None
            task.lease_expires_at = None
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
        domain_channel_index=domain_channel_index,
    )
    # 分析版本戳：记录本条样本使用的规则版本与轮次快照哈希。
    if round_row is not None:
        sample.analysis_version = round_row.analysis_config_version or snapshot_rules_version(
            round_row.analysis_config_snapshot
        )
        sample.analysis_config_hash = round_row.analysis_config_hash
    else:
        sample.analysis_version = snapshot_rules_version(None)
    sample.analyzed_at = datetime.now(timezone.utc)
    sample.status = ensure_sample_transition(
        SampleStatus.RUNNING, _observation_status(sample, result)
    )
    sample.finished_at = datetime.now(timezone.utc)
    task.status = ensure_task_transition(task.status, TaskStatus.DONE)
    if attempt is not None:
        attempt.status = ensure_attempt_transition(attempt.status, AttemptStatus.SUCCEEDED)
        attempt.finished_at = datetime.now(timezone.utc)
    task.lease_owner = None
    task.lease_expires_at = None
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
    domain_channel_index: dict | None = None,
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
    round_row = db.get(MonitoringRound, task.round_id)
    snapshot_vocabulary = vocabulary_from_snapshot(
        round_row.analysis_config_snapshot if round_row is not None else None
    )
    vocabulary = snapshot_vocabulary or build_vocabulary(db, project_id, project=project)

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
        domain_channel_index=domain_channel_index,
    )
    if round_row is not None:
        new_sample.analysis_version = (
            round_row.analysis_config_version
            or snapshot_rules_version(round_row.analysis_config_snapshot)
        )
        new_sample.analysis_config_hash = round_row.analysis_config_hash
    else:
        new_sample.analysis_version = snapshot_rules_version(None)
    new_sample.analyzed_at = datetime.now(timezone.utc)
    new_sample.status = ensure_sample_transition(
        SampleStatus.RUNNING, _observation_status(new_sample, result)
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


def resample_sample(
    db: Session,
    *,
    project_id: uuid.UUID,
    sample_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """重采样：在同一轮次下新建一个逻辑样本（新的 sampling_no），重新请求 AI 平台。

    与 `replay_sample` 的区别：
    - replay 是同一任务的又一次执行尝试（attempt_no+1），用于核对同一次采样的稳定性；
    - resample 是新的逻辑样本（sampling_no+1、新 task），代表“再抽一次”，
      会进入统计分母，因此必须走新的任务与 outbox 事件。
    轮次已结束（completed/closed）时拒绝，避免向历史轮次追加数据。
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

    round_row = db.scalar(
        select(MonitoringRound)
        .where(
            MonitoringRound.project_id == project_id,
            MonitoringRound.id == task.round_id,
        )
        .with_for_update()
    )
    if round_row is None:
        raise ProjectAccessError("monitoring_round not found in this project")
    if round_row.status not in (RoundStatus.PLANNING, RoundStatus.RUNNING):
        raise TaskRejectedError("本轮次已结束，不能重采样；请新建轮次后再抽")

    next_sampling_no = (
        db.scalar(
            select(func.coalesce(func.max(MonitoringTask.sampling_no), 0)).where(
                MonitoringTask.project_id == project_id,
                MonitoringTask.round_id == task.round_id,
                MonitoringTask.question_version_id == task.question_version_id,
                MonitoringTask.engine_entry_id == task.engine_entry_id,
            )
        )
        or 0
    ) + 1

    new_task = MonitoringTask(
        project_id=project_id,
        round_id=task.round_id,
        question_version_id=task.question_version_id,
        engine_entry_id=task.engine_entry_id,
        sampling_no=next_sampling_no,
        sampling_mode=task.sampling_mode,
        status=TaskStatus.PENDING,
        created_by=actor_id,
    )
    db.add(new_task)
    db.flush()
    emit_event(
        db,
        project_id=project_id,
        topic="monitoring.task.execute",
        payload={
            "project_id": str(project_id),
            "task_id": str(new_task.id),
            "round_id": str(round_row.id),
            "sampling_no": next_sampling_no,
            "source_sample_id": str(source.id),
        },
    )
    return {
        "task_id": str(new_task.id),
        "round_id": str(round_row.id),
        "sampling_no": next_sampling_no,
        "status": new_task.status.value,
        "source_sample_id": str(source.id),
        "outbox_topic": "monitoring.task.execute",
        "requested_at": (now or datetime.now(timezone.utc)).isoformat(),
    }


def reanalyze_sample(
    db: Session,
    *,
    project_id: uuid.UUID,
    sample_id: uuid.UUID,
    now: datetime | None = None,
    published_index: dict | None = None,
    domain_channel_index: dict | None = None,
) -> dict[str, Any]:
    """重分析：不请求 AI 平台，用样本已留存的原始回答重算派生字段。

    适用：识别规则/品牌词表/引用归属规则升级后，复核历史样本。
    - 不新建任务、不新建样本，统计分母不变；
    - 只更新 brand_mentioned / brand_identified、引用归属与状态，
      原始回答与采样时间保持原样；
    - 轮次有测量快照时按快照词表重算，保证与同轮其他样本口径一致。
    """
    source = db.scalar(
        select(MonitoringSample).where(
            MonitoringSample.project_id == project_id,
            MonitoringSample.id == sample_id,
        )
    )
    if source is None:
        raise ProjectAccessError("monitoring_sample not found in this project")
    if source.status not in (
        SampleStatus.HIT,
        SampleStatus.MISS,
        SampleStatus.NO_ANSWER_SURFACE,
    ):
        raise TaskRejectedError("只有已产出答案的样本可重分析")

    task = db.get(MonitoringTask, source.task_id)
    if task is None:
        raise ProjectAccessError("monitoring_task not found in this project")
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectAccessError("project not found")
    round_row = db.get(MonitoringRound, task.round_id)
    snapshot_vocabulary = vocabulary_from_snapshot(
        round_row.analysis_config_snapshot if round_row is not None else None
    )
    vocabulary = snapshot_vocabulary or build_vocabulary(db, project_id, project=project)

    if isinstance(source.raw_response, dict):
        payload = parse_raw_response(source.raw_response)
    else:
        payload = AnswerPayload()
    payload.text = source.raw_answer or payload.text
    payload.trace_id = source.trace_id
    # 重分析的目的就是按新规则重算：丢弃旧判定，交给词表重新算。
    payload.brand_mentioned = None
    payload.brand_identified = None
    if payload.answer_kind is None:
        payload.answer_kind = source.answer_kind

    result = apply_answer_payload(
        db,
        source,
        payload,
        brand_terms=vocabulary.mention_terms,
        brand_domains=vocabulary.owned_domains,
        brand_identifiers=vocabulary.identifier_terms,
        published_index=published_index,
        domain_channel_index=domain_channel_index,
    )
    if round_row is not None:
        source.analysis_version = (
            round_row.analysis_config_version
            or snapshot_rules_version(round_row.analysis_config_snapshot)
        )
        source.analysis_config_hash = round_row.analysis_config_hash
    else:
        source.analysis_version = snapshot_rules_version(None)
    source.analyzed_at = now or datetime.now(timezone.utc)
    # 重分析是派生状态重算，不是执行尝试：允许在 hit/miss/no_answer_surface 之间切换。
    source.status = _observation_status(source, result)
    db.flush()
    return {
        "sample_id": str(source.id),
        "task_id": str(task.id),
        "status": source.status.value,
        "brand_mentioned": result["brand_mentioned"],
        "brand_identified": result["brand_identified"],
        "citation_count": result["citation_count"],
        "analysis_version": source.analysis_version,
        "analyzed_at": source.analyzed_at.isoformat() if source.analyzed_at else None,
    }


def requeue_rate_limited_task(
    db: Session,
    *,
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    note: str,
) -> bool:
    """把限流失败的任务退回 pending，等待下一次退避重试。

    只允许 RUNNING/PENDING 的任务走这条路径：failed 是终态，必须人工补录或新建
    任务，不能把终态改回 pending。失败的 sample/attempt 保留在原 attempt 号下，
    重试会自然使用下一个 attempt_no。
    """
    task = db.scalar(
        select(MonitoringTask).where(
            MonitoringTask.project_id == project_id,
            MonitoringTask.id == task_id,
        )
    )
    if task is None or task.status not in (TaskStatus.RUNNING, TaskStatus.PENDING):
        return False
    if task.status == TaskStatus.RUNNING:
        task.status = ensure_task_transition(task.status, TaskStatus.PENDING)
    task.lease_owner = None
    task.lease_expires_at = None
    db.flush()
    logger.warning(
        "monitoring task requeued after rate limit",
        extra={
            "fields": {
                "project_id": str(project_id),
                "task_id": str(task_id),
                "note": note,
            }
        },
    )
    return True


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
    # 观测口径的渠道域名索引同样整批复用；渠道台账在补跑期间不变
    domain_channel_index = build_domain_channel_index(db, project_id) if task_ids else None
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
                domain_channel_index=domain_channel_index,
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
