"""固定周期复测：计划到期自动建轮、生成 API、应用内、网页端与手机客户端任务。

设计边界：
- API 入口任务写入事务性 outbox，由现有 Worker 自动采样；
- `app_search` / `web_user` / `app_user` 入口只建 pending 任务，不写 outbox，继续走工作台人工采样；
- 网页端任务用于“真实用户前端”基线：人工打开官方网页、新开对话、回填回答与快照；
- 手机客户端任务用于“App 真实回答”基线：必须与网页端分开入口、分开建任务、分开统计；
- 一轮内同时包含品牌题和通用题，统计层仍按题目类型分开呈现；
- 同一计划只允许一个 planning/running 轮次，上一轮未结束则跳过本次并推进下一次时间。
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, TaskRejectedError
from app.models import (
    AiEngine,
    AiEngineEntry,
    MonitoringRetestPlan,
    MonitoringRound,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    EngineEntryType,
    QuestionStatus,
    RoundStatus,
    SamplingMode,
    TaskStatus,
)
from app.services.audit import record_audit
from app.services.monitoring_batch import create_round
from app.services.outbox import emit_event
from app.services.state_machine import ensure_round_transition

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
ALLOWED_ENTRY_SCOPE = {
    EngineEntryType.API.value,
    EngineEntryType.APP_SEARCH.value,
    EngineEntryType.WEB_USER.value,
    EngineEntryType.APP_USER.value,
}
DEFAULT_ENTRY_SCOPE = ["api", "app_search"]
MAX_INTERVAL_DAYS = 365
MAX_SAMPLES_PER_CELL = 10


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc)
    return value.astimezone(timezone.utc)


def _clean_name(name: str) -> str:
    value = name.strip()
    if not value:
        raise BusinessValidationError("复测计划名称不能为空")
    if len(value) > 128:
        raise BusinessValidationError("复测计划名称不能超过 128 字")
    return value


def _clean_scope(entry_scope: list[str] | None) -> list[str]:
    scope = [str(item) for item in (entry_scope or DEFAULT_ENTRY_SCOPE)]
    unknown = sorted(set(scope) - ALLOWED_ENTRY_SCOPE)
    if unknown:
        raise BusinessValidationError(
            f"不支持的入口范围：{', '.join(unknown)}；固定周期只支持 api / app_search / web_user / app_user"
        )
    if not scope:
        raise BusinessValidationError("复测计划至少选择一个入口范围")
    # 去重并固定顺序，避免同一计划因前端勾选顺序产生不同 payload。
    return [
        item
        for item in (
            EngineEntryType.API.value,
            EngineEntryType.APP_SEARCH.value,
            EngineEntryType.WEB_USER.value,
            EngineEntryType.APP_USER.value,
        )
        if item in scope
    ]


def _clean_engine_codes(engine_codes: list[str] | None) -> list[str]:
    """引擎范围去重、转小写；空列表代表沿用全部启用 API 引擎。"""
    codes: list[str] = []
    for item in engine_codes or []:
        code = str(item).strip().casefold()
        if code and code not in codes:
            codes.append(code)
    if len(codes) > 20:
        raise BusinessValidationError("复测计划最多指定 20 个引擎")
    return codes


def _validate_engine_codes(
    db: Session, engine_codes: list[str], entry_scope: list[str] | None = None
) -> None:
    """建计划时就把未知、停用、指定范围内无入口的引擎拒绝掉。

    不能只校验 API：单引擎网页端复测可能只有 `web_user` 入口，没有 API。
    """
    if not engine_codes:
        return
    rows = db.execute(
        select(AiEngine.code, AiEngine.is_active).where(AiEngine.code.in_(engine_codes))
    ).all()
    found = {code for code, _active in rows}
    missing = sorted(set(engine_codes) - found)
    if missing:
        raise BusinessValidationError(f"未知引擎：{', '.join(missing)}")
    inactive = sorted(code for code, active in rows if not active)
    if inactive:
        raise BusinessValidationError(f"引擎未启用：{', '.join(inactive)}")

    scope = _clean_scope(entry_scope)
    scope_labels = {
        EngineEntryType.API.value: "API",
        EngineEntryType.APP_SEARCH.value: "应用内",
        EngineEntryType.WEB_USER.value: "网页端",
        EngineEntryType.APP_USER.value: "手机客户端",
    }
    missing_by_type: list[str] = []
    for entry_type in (EngineEntryType(item) for item in scope):
        if entry_type == EngineEntryType.API:
            branch = and_(
                AiEngineEntry.entry_type == EngineEntryType.API,
                AiEngineEntry.is_active.is_(True),
                AiEngineEntry.supports_search.is_(True),
            )
        else:
            # 应用内/网页端/手机客户端走人工，入口停用也可以作为待手测入口。
            branch = AiEngineEntry.entry_type == entry_type
        available = set(
            db.scalars(
                select(AiEngine.code)
                .join(AiEngineEntry, AiEngineEntry.engine_id == AiEngine.id)
                .where(AiEngine.code.in_(engine_codes), branch)
            ).all()
        )
        missing = sorted(set(engine_codes) - available)
        if missing:
            missing_by_type.append(
                f"{scope_labels[entry_type.value]}: {', '.join(missing)}"
            )
    if missing_by_type:
        raise BusinessValidationError(
            "引擎缺少所选入口类型：" + "；".join(missing_by_type)
        )


def _advance_next_run(next_run_at: datetime, interval_days: int, now: datetime) -> datetime:
    """跳过已经错过的周期，只排未来最近一次，避免一次补出多轮。"""
    interval = timedelta(days=interval_days)
    if next_run_at > now:
        return next_run_at
    steps = math.floor((now - next_run_at).total_seconds() / interval.total_seconds()) + 1
    return next_run_at + interval * steps


def _active_question_versions(
    db: Session, project_id: uuid.UUID
) -> list[tuple[Question, QuestionVersion]]:
    return list(
        db.execute(
            select(Question, QuestionVersion)
            .join(
                QuestionVersion,
                and_(
                    QuestionVersion.question_id == Question.id,
                    QuestionVersion.version_no == Question.current_version_no,
                ),
            )
            .where(
                Question.project_id == project_id,
                QuestionVersion.project_id == project_id,
                Question.status == QuestionStatus.ACTIVE,
            )
            .order_by(Question.priority, Question.code)
        ).all()
    )


def _select_api_entries(
    db: Session, engine_codes: list[str] | None = None
) -> list[AiEngineEntry]:
    """每个启用引擎取一个有效 API 入口；engine_codes 为空时取全部启用引擎。"""
    conditions = [
        AiEngine.is_active.is_(True),
        AiEngineEntry.is_active.is_(True),
        AiEngineEntry.supports_search.is_(True),
        AiEngineEntry.entry_type == EngineEntryType.API,
    ]
    if engine_codes:
        conditions.append(AiEngine.code.in_(engine_codes))
    rows = db.execute(
        select(AiEngine, AiEngineEntry)
        .join(AiEngineEntry, AiEngineEntry.engine_id == AiEngine.id)
        .where(*conditions)
        .order_by(AiEngine.code, AiEngineEntry.created_at, AiEngineEntry.id)
    ).all()
    picked: dict[uuid.UUID, AiEngineEntry] = {}
    for engine, entry in rows:
        picked.setdefault(engine.id, entry)
    return list(picked.values())


def _select_app_search_entries(
    db: Session, engine_codes: list[str] | None = None
) -> list[AiEngineEntry]:
    """应用内入口允许是停用状态：它们本来就不自动采集，只作为人工入口。"""
    return _select_manual_entries(db, EngineEntryType.APP_SEARCH, engine_codes)


def _select_manual_entries(
    db: Session,
    entry_type: EngineEntryType,
    engine_codes: list[str] | None = None,
) -> list[AiEngineEntry]:
    """每个启用引擎取一个指定人工入口；只建任务，不自动调用。

    人工入口不需要 API 凭据，因此允许入口处于停用状态；但引擎必须启用。
    """
    conditions = [
        AiEngine.is_active.is_(True),
        AiEngineEntry.entry_type == entry_type,
    ]
    if engine_codes:
        conditions.append(AiEngine.code.in_(engine_codes))
    rows = db.execute(
        select(AiEngine, AiEngineEntry)
        .join(AiEngineEntry, AiEngineEntry.engine_id == AiEngine.id)
        .where(*conditions)
        .order_by(AiEngine.code, AiEngineEntry.created_at, AiEngineEntry.id)
    ).all()
    picked: dict[uuid.UUID, AiEngineEntry] = {}
    for engine, entry in rows:
        picked.setdefault(engine.id, entry)
    return list(picked.values())


def _select_entries(
    db: Session, entry_scope: list[str], engine_codes: list[str] | None = None
) -> list[AiEngineEntry]:
    entries: list[AiEngineEntry] = []
    if EngineEntryType.API.value in entry_scope:
        entries.extend(_select_api_entries(db, engine_codes))
    if EngineEntryType.APP_SEARCH.value in entry_scope:
        entries.extend(_select_app_search_entries(db, engine_codes))
    if EngineEntryType.WEB_USER.value in entry_scope:
        entries.extend(_select_manual_entries(db, EngineEntryType.WEB_USER, engine_codes))
    if EngineEntryType.APP_USER.value in entry_scope:
        entries.extend(_select_manual_entries(db, EngineEntryType.APP_USER, engine_codes))
    return entries


def _latest_round(db: Session, plan: MonitoringRetestPlan) -> MonitoringRound | None:
    return db.scalar(
        select(MonitoringRound)
        .where(
            MonitoringRound.project_id == plan.project_id,
            MonitoringRound.retest_plan_id == plan.id,
        )
        .order_by(MonitoringRound.scheduled_for.desc(), MonitoringRound.seq.desc())
        .limit(1)
    )


def plan_payload(db: Session, plan: MonitoringRetestPlan) -> dict[str, Any]:
    latest = _latest_round(db, plan)
    return {
        "id": str(plan.id),
        "name": plan.name,
        "interval_days": plan.interval_days,
        "first_run_at": plan.first_run_at,
        "next_run_at": plan.next_run_at,
        "entry_scope": list(plan.entry_scope or []),
        "engine_codes": list(plan.engine_codes or []),
        "samples_per_cell": plan.samples_per_cell,
        "enabled": plan.enabled,
        "last_run_at": plan.last_run_at,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
        "latest_round_id": str(latest.id) if latest else None,
        "latest_round_name": latest.name if latest else None,
        "latest_round_status": latest.status.value if latest else None,
        "latest_round_scheduled_for": latest.scheduled_for if latest else None,
    }


def list_plans(db: Session, project_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(MonitoringRetestPlan)
        .where(MonitoringRetestPlan.project_id == project_id)
        .order_by(MonitoringRetestPlan.enabled.desc(), MonitoringRetestPlan.next_run_at, MonitoringRetestPlan.created_at)
    ).all()
    return [plan_payload(db, row) for row in rows]


def create_plan(
    db: Session,
    *,
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    name: str,
    interval_days: int,
    first_run_at: datetime,
    entry_scope: list[str] | None = None,
    engine_codes: list[str] | None = None,
    samples_per_cell: int = 1,
    enabled: bool = True,
) -> MonitoringRetestPlan:
    if not 1 <= interval_days <= MAX_INTERVAL_DAYS:
        raise BusinessValidationError(f"复测周期必须在 1–{MAX_INTERVAL_DAYS} 天之间")
    if not 1 <= samples_per_cell <= MAX_SAMPLES_PER_CELL:
        raise BusinessValidationError(f"每格采样次数必须在 1–{MAX_SAMPLES_PER_CELL} 之间")
    cleaned_scope = _clean_scope(entry_scope)
    cleaned_engine_codes = _clean_engine_codes(engine_codes)
    _validate_engine_codes(db, cleaned_engine_codes, cleaned_scope)
    first_run_at_utc = _as_utc(first_run_at)
    now = _now()
    row = MonitoringRetestPlan(
        project_id=project_id,
        name=_clean_name(name),
        interval_days=interval_days,
        first_run_at=first_run_at_utc,
        next_run_at=first_run_at_utc if first_run_at_utc > now else now,
        entry_scope=cleaned_scope,
        engine_codes=cleaned_engine_codes,
        samples_per_cell=samples_per_cell,
        enabled=enabled,
        created_by=actor_id,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise TaskRejectedError("同名复测计划已存在", code="retest_plan_conflict") from exc
    record_audit(
        db,
        project_id=project_id,
        actor_id=actor_id,
        action="monitoring.retest_plan_create",
        target_type="monitoring_retest_plan",
        target_id=row.id,
        payload={
            "name": row.name,
            "interval_days": row.interval_days,
            "first_run_at": row.first_run_at.isoformat(),
            "next_run_at": row.next_run_at.isoformat(),
            "entry_scope": row.entry_scope,
            "engine_codes": row.engine_codes,
            "samples_per_cell": row.samples_per_cell,
            "enabled": row.enabled,
        },
    )
    return row


def update_plan(
    db: Session,
    *,
    project_id: uuid.UUID,
    plan_id: uuid.UUID,
    actor_id: uuid.UUID,
    name: str | None = None,
    interval_days: int | None = None,
    first_run_at: datetime | None = None,
    entry_scope: list[str] | None = None,
    engine_codes: list[str] | None = None,
    samples_per_cell: int | None = None,
    enabled: bool | None = None,
) -> MonitoringRetestPlan:
    plan = db.scalar(
        select(MonitoringRetestPlan).where(
            MonitoringRetestPlan.project_id == project_id,
            MonitoringRetestPlan.id == plan_id,
        )
    )
    if plan is None:
        raise TaskRejectedError("复测计划不存在", code="retest_plan_not_found")
    now = _now()
    recalc_next = False
    if name is not None:
        plan.name = _clean_name(name)
    if interval_days is not None:
        if not 1 <= interval_days <= MAX_INTERVAL_DAYS:
            raise BusinessValidationError(f"复测周期必须在 1–{MAX_INTERVAL_DAYS} 天之间")
        plan.interval_days = interval_days
        recalc_next = True
    if first_run_at is not None:
        plan.first_run_at = _as_utc(first_run_at)
        recalc_next = True
    if entry_scope is not None:
        plan.entry_scope = _clean_scope(entry_scope)
    if engine_codes is not None:
        cleaned_engine_codes = _clean_engine_codes(engine_codes)
        _validate_engine_codes(db, cleaned_engine_codes, list(plan.entry_scope or []))
        plan.engine_codes = cleaned_engine_codes
    elif entry_scope is not None and plan.engine_codes:
        _validate_engine_codes(db, list(plan.engine_codes), list(plan.entry_scope or []))
    if samples_per_cell is not None:
        if not 1 <= samples_per_cell <= MAX_SAMPLES_PER_CELL:
            raise BusinessValidationError(f"每格采样次数必须在 1–{MAX_SAMPLES_PER_CELL} 之间")
        plan.samples_per_cell = samples_per_cell
    if enabled is not None:
        plan.enabled = enabled
        if enabled and plan.next_run_at <= now:
            recalc_next = True
    if recalc_next:
        anchor = plan.first_run_at if plan.first_run_at > now else now
        plan.next_run_at = anchor
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise TaskRejectedError("同名复测计划已存在", code="retest_plan_conflict") from exc
    record_audit(
        db,
        project_id=project_id,
        actor_id=actor_id,
        action="monitoring.retest_plan_update",
        target_type="monitoring_retest_plan",
        target_id=plan.id,
        payload={
            "name": plan.name,
            "interval_days": plan.interval_days,
            "first_run_at": plan.first_run_at.isoformat(),
            "next_run_at": plan.next_run_at.isoformat(),
            "entry_scope": plan.entry_scope,
            "engine_codes": plan.engine_codes,
            "samples_per_cell": plan.samples_per_cell,
            "enabled": plan.enabled,
        },
    )
    return plan


def _create_round_from_plan(
    db: Session,
    *,
    plan: MonitoringRetestPlan,
    scheduled_for: datetime,
    skip_if_open: bool,
) -> dict[str, Any]:
    existing_slot = db.scalar(
        select(MonitoringRound).where(
            MonitoringRound.project_id == plan.project_id,
            MonitoringRound.retest_plan_id == plan.id,
            MonitoringRound.scheduled_for == scheduled_for,
        )
    )
    if existing_slot is not None:
        return {
            "status": "skipped",
            "reason": "round_slot_exists",
            "round_id": str(existing_slot.id),
        }

    open_round = db.scalar(
        select(MonitoringRound)
        .where(
            MonitoringRound.project_id == plan.project_id,
            MonitoringRound.retest_plan_id == plan.id,
            MonitoringRound.status.in_((RoundStatus.PLANNING, RoundStatus.RUNNING)),
        )
        .order_by(MonitoringRound.seq.desc())
        .limit(1)
    )
    if open_round is not None:
        if skip_if_open:
            return {
                "status": "skipped",
                "reason": "previous_round_open",
                "round_id": str(open_round.id),
            }
        raise TaskRejectedError(
            "该计划上一轮还未结束，不能立即执行下一轮",
            code="retest_previous_round_open",
        )

    questions = _active_question_versions(db, plan.project_id)
    entries = _select_entries(
        db, list(plan.entry_scope or []), list(plan.engine_codes or [])
    )
    if not questions:
        return {"status": "skipped", "reason": "no_active_question"}
    if not entries:
        return {"status": "skipped", "reason": "no_entry_in_scope"}

    local_slot = scheduled_for.astimezone(LOCAL_TZ)
    round_row = create_round(
        db,
        project_id=plan.project_id,
        actor_id=plan.created_by,
        name=f"{plan.name} {local_slot:%Y-%m-%d %H:%M}",
        is_baseline=False,
        planned_at=scheduled_for,
        retest_plan_id=plan.id,
        scheduled_for=scheduled_for,
    )

    created_tasks: list[MonitoringTask] = []
    for _question, version in questions:
        for entry in entries:
            for sampling_no in range(1, plan.samples_per_cell + 1):
                task = MonitoringTask(
                    project_id=plan.project_id,
                    round_id=round_row.id,
                    question_version_id=version.id,
                    engine_entry_id=entry.id,
                    sampling_no=sampling_no,
                    trace_id=uuid.uuid4().hex,
                    sampling_mode=SamplingMode.SEARCH_ON,
                    status=TaskStatus.PENDING,
                    created_by=plan.created_by,
                )
                db.add(task)
                created_tasks.append(task)
    db.flush()

    if round_row.status == RoundStatus.PLANNING:
        round_row.status = ensure_round_transition(round_row.status, RoundStatus.RUNNING)

    entry_type_by_id = {entry.id: entry.entry_type for entry in entries}
    api_task_ids = [
        str(task.id)
        for task in created_tasks
        if entry_type_by_id[task.engine_entry_id] == EngineEntryType.API
    ]
    for task_id in api_task_ids:
        emit_event(
            db,
            project_id=plan.project_id,
            topic="monitoring.task.execute",
            payload={
                "project_id": str(plan.project_id),
                "task_id": task_id,
                "round_id": str(round_row.id),
            },
        )

    record_audit(
        db,
        project_id=plan.project_id,
        actor_id=plan.created_by,
        action="monitoring.retest_round_create",
        target_type="monitoring_round",
        target_id=round_row.id,
        payload={
            "retest_plan_id": str(plan.id),
            "scheduled_for": scheduled_for.isoformat(),
            "question_count": len(questions),
            "entry_count": len(entries),
            "engine_codes": list(plan.engine_codes or []),
            "samples_per_cell": plan.samples_per_cell,
            "created_task_count": len(created_tasks),
            "api_task_count": len(api_task_ids),
            "manual_task_count": len(created_tasks) - len(api_task_ids),
        },
    )
    db.flush()
    return {
        "status": "created",
        "round_id": str(round_row.id),
        "created_task_count": len(created_tasks),
        "api_task_count": len(api_task_ids),
        "manual_task_count": len(created_tasks) - len(api_task_ids),
    }


def run_due_retest_plans(db: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """扫描到期计划；每个计划用 savepoint 隔离，单个计划失败不拖垮其他计划。"""
    now_utc = _as_utc(now) if now is not None else _now()
    plans = list(
        db.scalars(
            select(MonitoringRetestPlan)
            .where(
                MonitoringRetestPlan.enabled.is_(True),
                MonitoringRetestPlan.next_run_at <= now_utc,
            )
            .order_by(MonitoringRetestPlan.next_run_at, MonitoringRetestPlan.created_at)
            .with_for_update(skip_locked=True)
        ).all()
    )
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for plan in plans:
        scheduled_for = plan.next_run_at
        try:
            with db.begin_nested():
                result = _create_round_from_plan(
                    db,
                    plan=plan,
                    scheduled_for=scheduled_for,
                    skip_if_open=True,
                )
                if result["status"] == "skipped":
                    plan.next_run_at = _advance_next_run(
                        scheduled_for, plan.interval_days, now_utc
                    )
                    record_audit(
                        db,
                        project_id=plan.project_id,
                        actor_id=plan.created_by,
                        action="monitoring.retest_skip",
                        target_type="monitoring_retest_plan",
                        target_id=plan.id,
                        payload={
                            "reason": result.get("reason"),
                            "scheduled_for": scheduled_for.isoformat(),
                            "round_id": result.get("round_id"),
                        },
                    )
                    skipped.append(
                        {
                            "plan_id": str(plan.id),
                            "plan_name": plan.name,
                            "scheduled_for": scheduled_for.isoformat(),
                            **result,
                        }
                    )
                else:
                    plan.last_run_at = now_utc
                    plan.next_run_at = _advance_next_run(
                        scheduled_for, plan.interval_days, now_utc
                    )
                    created.append(
                        {
                            "plan_id": str(plan.id),
                            "plan_name": plan.name,
                            "scheduled_for": scheduled_for.isoformat(),
                            **result,
                        }
                    )
        except Exception as exc:  # noqa: BLE001 - 单计划失败要保留其他计划的建轮结果
            failed.append(
                {
                    "plan_id": str(plan.id),
                    "plan_name": plan.name,
                    "scheduled_for": scheduled_for.isoformat(),
                    "reason": str(exc),
                }
            )
    return {
        "due_plan_count": len(plans),
        "created_count": len(created),
        "skipped_count": len(skipped),
        "failed_count": len(failed),
        "created": created,
        "skipped": skipped,
        "failed": failed,
    }


def run_plan_now(
    db: Session,
    *,
    project_id: uuid.UUID,
    plan_id: uuid.UUID,
    actor_id: uuid.UUID,
    now: datetime | None = None,
) -> dict[str, Any]:
    plan = db.scalar(
        select(MonitoringRetestPlan)
        .where(
            MonitoringRetestPlan.project_id == project_id,
            MonitoringRetestPlan.id == plan_id,
        )
        .with_for_update()
    )
    if plan is None:
        raise TaskRejectedError("复测计划不存在", code="retest_plan_not_found")
    now_utc = _as_utc(now) if now is not None else _now()
    # 立即执行用当前时间作为槽位，不把未来计划槽位提前消耗掉；
    # 若计划已经到期，则顺手推进到下一个未来周期，避免下一次 beat 再尝试同一槽位。
    scheduled_for = now_utc
    result = _create_round_from_plan(
        db,
        plan=plan,
        scheduled_for=scheduled_for,
        skip_if_open=False,
    )
    if result["status"] == "skipped":
        raise TaskRejectedError(
            f"当前无法执行复测：{result['reason']}", code=result["reason"]
        )
    plan.last_run_at = now_utc
    if plan.next_run_at <= now_utc:
        plan.next_run_at = _advance_next_run(plan.next_run_at, plan.interval_days, now_utc)
    record_audit(
        db,
        project_id=project_id,
        actor_id=actor_id,
        action="monitoring.retest_run_now",
        target_type="monitoring_retest_plan",
        target_id=plan.id,
        payload={"scheduled_for": scheduled_for.isoformat(), **result},
    )
    db.flush()
    return {
        "plan_id": str(plan.id),
        "plan_name": plan.name,
        "scheduled_for": scheduled_for,
        **result,
    }
