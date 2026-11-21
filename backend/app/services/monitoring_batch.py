"""监测轮次与“启用题目 × 启用平台”批量生成。

口径（与 C 对齐，见 B4 实现方案）：
- 基线由 `is_baseline=true` 识别，不靠 `seq=1`；全项目只允许一条基线，幂等 get-or-create；
- `seq = COALESCE(MAX(seq), 0) + 1`，空项目 MAX 返回 NULL 必须兜底；
- 批量任务幂等键：round_id + question_version_id + engine_entry_id + sampling_no；
- 基线分母按当前 ACTIVE 题目 × ACTIVE 且可联网的入口动态计算，不再写死 4 个平台；
- 业务不完整返回 `200 + complete=false + skipped_reason`，不抛 409；
- 并发：批量生成锁轮次行；仅建基线锁 projects 行；唯一约束只作兜底，
  禁止捕获 IntegrityError 后按 seq+1 直接重插。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.models import (
    AiEngine,
    AiEngineEntry,
    MonitoringRound,
    MonitoringTask,
    Project,
    Question,
    QuestionVersion,
)
from app.models.enums import EngineEntryType, QuestionStatus, RoundStatus, SamplingMode, TaskStatus
from app.services.audit import record_audit
from app.services.measurement_snapshot import attach_measurement_snapshot, build_measurement_snapshot
from app.services.project_scope import require_scoped_row
from app.services.stat_snapshots import create_round_snapshot
from app.services.state_machine import ensure_round_transition


def _count_active_engines(db: Session) -> int:
    """当前启用引擎数；基线分母随启停状态变化，不写死平台数。"""
    return int(
        db.scalar(
            select(func.count()).select_from(AiEngine).where(AiEngine.is_active.is_(True))
        )
        or 0
    )


def round_payload(row: MonitoringRound) -> dict[str, Any]:
    """轮次记录转响应字典。"""
    return {
        "id": str(row.id),
        "seq": row.seq,
        "name": row.name,
        "is_baseline": row.is_baseline,
        "status": row.status.value if hasattr(row.status, "value") else str(row.status),
        "planned_at": row.planned_at,
        "created_at": row.created_at,
    }


def list_rounds(
    db: Session,
    *,
    project_id: uuid.UUID,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    total = (
        db.scalar(
            select(func.count())
            .select_from(MonitoringRound)
            .where(MonitoringRound.project_id == project_id)
        )
        or 0
    )
    rows = db.scalars(
        select(MonitoringRound)
        .where(MonitoringRound.project_id == project_id)
        .order_by(MonitoringRound.is_baseline.desc(), MonitoringRound.seq.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [round_payload(row) for row in rows], total


def create_round(
    db: Session,
    *,
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    name: str | None,
    is_baseline: bool,
    planned_at: datetime | None,
    retest_plan_id: uuid.UUID | None = None,
    scheduled_for: datetime | None = None,
) -> MonitoringRound:
    """新建轮次；基线走幂等 get-or-create，已有基线直接返回已有记录。"""
    if is_baseline:
        # 建基线并发：锁 projects 行按项目串行化 get-or-create；唯一约束只作兜底，
        # 冲突时回查已有基线，不按 seq+1 重插。非基线轮次不加 projects 行锁，seq 竞态由约束兜底。
        db.execute(select(Project.id).where(Project.id == project_id).with_for_update())
        existing = db.scalar(
            select(MonitoringRound).where(
                MonitoringRound.project_id == project_id,
                MonitoringRound.is_baseline.is_(True),
            )
        )
        if existing is not None:
            return existing

    next_seq = (
        db.scalar(
            select(func.coalesce(func.max(MonitoringRound.seq), 0)).where(
                MonitoringRound.project_id == project_id
            )
        )
        or 0
    ) + 1
    round_name = name or ("基线轮次" if is_baseline else f"第 {next_seq} 轮")

    row = MonitoringRound(
        project_id=project_id,
        seq=next_seq,
        name=round_name,
        is_baseline=is_baseline,
        planned_at=planned_at,
        status=RoundStatus.PLANNING,
        created_by=actor_id,
        retest_plan_id=retest_plan_id,
        scheduled_for=scheduled_for,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if is_baseline:
            existing = db.scalar(
                select(MonitoringRound).where(
                    MonitoringRound.project_id == project_id,
                    MonitoringRound.is_baseline.is_(True),
                )
            )
            if existing is not None:
                return existing
        raise ConflictError(
            "轮次创建冲突，请先刷新后重试", code="monitoring_round_conflict"
        ) from exc
    # 轮次进入执行前固定测量快照：品牌词表、竞品与规则版本。
    # 中途修改品牌配置只影响下一轮，不改变本轮样本口径。
    attach_measurement_snapshot(row, build_measurement_snapshot(db, project_id=project_id))
    record_audit(
        db,
        project_id=project_id,
        actor_id=actor_id,
        action="monitoring.round_create",
        target_type="monitoring_round",
        target_id=row.id,
        payload={"is_baseline": is_baseline, "seq": next_seq, "name": round_name, "retest_plan_id": str(retest_plan_id) if retest_plan_id else None, "scheduled_for": scheduled_for.isoformat() if scheduled_for else None},
    )
    return row


def _group_questions(
    db: Session, project_id: uuid.UUID
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """把项目题目分成 eligible / inactive / version_missing，均按 code 升序。"""
    questions = db.scalars(select(Question).where(Question.project_id == project_id)).all()
    eligible: list[dict[str, Any]] = []
    inactive: list[dict[str, Any]] = []
    version_missing: list[dict[str, Any]] = []

    for question in questions:
        version = db.scalar(
            select(QuestionVersion).where(
                QuestionVersion.question_id == question.id,
                QuestionVersion.version_no == question.current_version_no,
            )
        )
        item: dict[str, Any] = {
            "id": str(question.id),
            "code": question.code,
            "title": question.title,
            "status": question.status.value,
        }
        if question.status != QuestionStatus.ACTIVE:
            inactive.append(item)
        elif version is None:
            version_missing.append(item)
        else:
            eligible.append({**item, "version_id": str(version.id), "version": version})

    eligible.sort(key=lambda x: x["code"])
    inactive.sort(key=lambda x: x["code"])
    version_missing.sort(key=lambda x: x["code"])
    return eligible, inactive, version_missing


def _select_engine_entries(
    db: Session,
    entry_types: tuple[EngineEntryType, ...] | None = None,
) -> tuple[list[tuple[AiEngine, AiEngineEntry]], int]:
    """按入口类型选择有效入口。

    默认（`entry_types=None`）：每个启用引擎只取首个有效入口，保持旧行为。
    指定类型：每个启用引擎 × 每种指定类型各取一条，允许同一引擎同时排
    API 与网页入口。第二个返回值是“缺失的引擎×入口类型组合数”，用于
    完整度判定；默认模式只统计完全没有入口的启用引擎。
    """
    rows = db.execute(
        select(AiEngine, AiEngineEntry)
        .join(AiEngineEntry, AiEngineEntry.engine_id == AiEngine.id)
        .where(
            AiEngine.is_active.is_(True),
            AiEngineEntry.is_active.is_(True),
            # 批量任务固定写 SEARCH_ON；没有联网能力的入口不能进入候选。
            AiEngineEntry.supports_search.is_(True),
        )
        .order_by(AiEngine.code, AiEngineEntry.created_at, AiEngineEntry.id)
    ).all()
    active_engine_ids = set(db.scalars(select(AiEngine.id).where(AiEngine.is_active.is_(True))).all())

    if entry_types is None:
        picked: dict[uuid.UUID, tuple[AiEngine, AiEngineEntry]] = {}
        for engine, entry in rows:
            if engine.id not in picked:
                picked[engine.id] = (engine, entry)
        missing = len(active_engine_ids - set(picked))
        return list(picked.values()), missing

    by_engine: dict[uuid.UUID, dict[EngineEntryType, tuple[AiEngine, AiEngineEntry]]] = {}
    for engine, entry in rows:
        if entry.entry_type in entry_types:
            by_engine.setdefault(engine.id, {}).setdefault(entry.entry_type, (engine, entry))

    picked_pairs: list[tuple[AiEngine, AiEngineEntry]] = []
    missing = 0
    for engine_id in active_engine_ids:
        entries = by_engine.get(engine_id, {})
        for entry_type in entry_types:
            pair = entries.get(entry_type)
            if pair is None:
                missing += 1
            else:
                picked_pairs.append(pair)
    picked_pairs.sort(key=lambda pair: (pair[0].code, pair[1].entry_type.value, pair[1].id))
    return picked_pairs, missing


def generate_tasks(
    db: Session,
    *,
    project_id: uuid.UUID,
    round_id: uuid.UUID,
    actor_id: uuid.UUID,
    expected_engine_count: int | None = None,
    entry_types: list[EngineEntryType] | None = None,
    samples_per_cell: int = 1,
) -> dict[str, Any]:
    """批量生成 题目版本 × 引擎入口 × 采样序号 的监测任务，幂等回写计数与完整度判定。

    基线分母 = 当前 ACTIVE 题目 × 当前 ACTIVE 可联网入口 × 每格采样次数。
    `expected_engine_count` 不传时按库内启用引擎数动态计算；脚本只跑部分平台时
    可显式传入实际选中平台数，避免把“部分诊断”误判成完整基线。
    `samples_per_cell` 控制同一题、同一入口的采样次数；默认 1 保持旧接口兼容，
    前端可按 3 次发起，用于观测提及率波动。
    """
    samples_per_cell = max(1, min(10, int(samples_per_cell)))
    round_row = require_scoped_row(
        db, MonitoringRound, project_id, resource="monitoring_round", id=round_id
    )

    # 批量生成并发：锁轮次行，再查/插任务；唯一约束只作兜底。
    db.execute(
        select(MonitoringRound.id)
        .where(
            MonitoringRound.id == round_id,
            MonitoringRound.project_id == project_id,
        )
        .with_for_update()
    )

    # 生成任务即实质开跑：计划中轮次自动进入 running；已完成/关闭轮次禁止再追加任务，
    # 否则会改变已冻结快照的分母。
    if round_row.status == RoundStatus.PLANNING:
        round_row.status = ensure_round_transition(round_row.status, RoundStatus.RUNNING)
    elif round_row.status in (RoundStatus.COMPLETED, RoundStatus.CLOSED):
        raise ConflictError("轮次已完成或关闭，不能追加任务", code="round_not_open")

    eligible, inactive, version_missing = _group_questions(db, project_id)
    requested_entry_types = tuple(sorted(set(entry_types), key=lambda item: item.value)) if entry_types else None
    engines, missing_entry_count = _select_engine_entries(db, requested_entry_types)
    engine_ids = {engine.id for engine, _ in engines}
    engine_count = len(engine_ids)
    engine_entry_count = len(engines)
    active_engine_count = _count_active_engines(db)
    expected_engine_count = (
        active_engine_count
        if expected_engine_count is None
        else max(0, int(expected_engine_count))
    )
    expected_entry_count = expected_engine_count * (len(requested_entry_types) if requested_entry_types else 1)

    requested = len(eligible) + len(inactive) + len(version_missing)
    expected = len(eligible) * engine_entry_count * samples_per_cell
    eligible_expected = len(eligible) * engine_entry_count * samples_per_cell

    # 契约 3.4：active 但当前版本缺失属于数据完整性阻断，整批不生成（generated=0）；
    # 未激活题目不进入基线分母，只作为运营提示返回。
    blocked_by_version = len(version_missing) > 0
    batch_eligible: list[dict[str, Any]] = [] if blocked_by_version else eligible

    existing = {
        (task.question_version_id, task.engine_entry_id, task.sampling_no): task
        for task in db.scalars(
            select(MonitoringTask).where(
                MonitoringTask.project_id == project_id,
                MonitoringTask.round_id == round_id,
            )
        )
    }

    created = 0
    reused = 0
    for item in batch_eligible:
        version_id = uuid.UUID(item["version_id"])
        for _, entry in engines:
            for sampling_no in range(1, samples_per_cell + 1):
                key = (version_id, entry.id, sampling_no)
                existing_task = existing.get(key)
                if existing_task is not None:
                    # 老数据补齐 trace；复用任务不换 trace，重试仍能串回同一轮。
                    if not existing_task.trace_id:
                        existing_task.trace_id = uuid.uuid4().hex
                    reused += 1
                    continue
                db.add(
                    MonitoringTask(
                        project_id=project_id,
                        round_id=round_row.id,
                        question_version_id=version_id,
                        engine_entry_id=entry.id,
                        sampling_no=sampling_no,
                        trace_id=uuid.uuid4().hex,
                        sampling_mode=SamplingMode.SEARCH_ON,
                        status=TaskStatus.PENDING,
                        created_by=actor_id,
                    )
                )
                created += 1
    db.flush()
    generated = created + reused

    # skipped_reason 主因优先级：版本缺失 > 无启用题目 > 引擎/入口不足。
    # 未激活题目不再阻塞基线：它们只是不进入分母，并在响应里单独列出。
    if version_missing:
        skipped_reason = "question_version_missing"
    elif not eligible:
        skipped_reason = "no_active_question"
    elif (
        expected_engine_count == 0
        or missing_entry_count
        or engine_count != expected_engine_count
    ):
        skipped_reason = "engine_entries_insufficient"
    else:
        skipped_reason = None

    complete = (
        expected > 0
        and generated == expected
        and engine_count == expected_engine_count
        and engine_entry_count == expected_entry_count
        and missing_entry_count == 0
        and len(version_missing) == 0
        and skipped_reason is None
    )

    result: dict[str, Any] = {
        "round_id": str(round_row.id),
        "requested_question_count": requested,
        "eligible_question_count": len(eligible),
        "expected_question_count": len(eligible),
        "inactive_question_count": len(inactive),
        "inactive_question_ids": [q["id"] for q in inactive],
        "inactive_questions": inactive,
        "question_version_missing_count": len(version_missing),
        "question_version_missing_question_ids": [q["id"] for q in version_missing],
        "engine_count": engine_count,
        "expected_engine_count": expected_engine_count,
        "engine_entry_count": engine_entry_count,
        "missing_engine_entry_count": missing_entry_count,
        "expected_engine_entry_count": expected_entry_count,
        "requested_entry_types": [item.value for item in requested_entry_types] if requested_entry_types else [],
        "samples_per_cell": samples_per_cell,
        "expected_task_count": expected,
        "eligible_expected_task_count": eligible_expected,
        "created_task_count": created,
        "reused_task_count": reused,
        "generated_task_count": generated,
        "complete": complete,
        "skipped_reason": skipped_reason,
    }

    record_audit(
        db,
        project_id=project_id,
        actor_id=actor_id,
        action="monitoring.tasks_batch_generate",
        target_type="monitoring_round",
        target_id=round_row.id,
        payload=result,
    )
    return result


def start_round(
    db: Session, *, project_id: uuid.UUID, round_id: uuid.UUID
) -> MonitoringRound:
    """计划中的轮次显式开始；已在 running 时幂等返回。"""
    round_row = require_scoped_row(
        db,
        MonitoringRound,
        project_id,
        resource="monitoring_round",
        for_update=True,
        id=round_id,
    )
    if round_row.status == RoundStatus.RUNNING:
        return round_row
    if round_row.status != RoundStatus.PLANNING:
        raise ConflictError("轮次已完成或关闭，不能重新开始", code="round_not_open")
    round_row.status = ensure_round_transition(round_row.status, RoundStatus.RUNNING)
    return round_row


def complete_round(
    db: Session, *, project_id: uuid.UUID, round_id: uuid.UUID, actor_id: uuid.UUID
) -> tuple[MonitoringRound, Any, dict[str, int]]:
    """轮次完成时自动冻结统计快照；已有快照复用，不覆盖历史结果。

    完成门槛是“所有任务进入可结算终态”：done 或 failed。
    pending/running 未完成；uncertain/cancelled 不能作为正式分母，必须处理后才能冻结。
    failed 进入失败分桶，不进入有效回答分母，但不再阻塞整轮收口。
    """
    from app.models import StatSnapshot

    round_row = require_scoped_row(
        db,
        MonitoringRound,
        project_id,
        resource="monitoring_round",
        for_update=True,
        id=round_id,
    )
    counts_rows = db.execute(
        select(MonitoringTask.status, func.count())
        .where(
            MonitoringTask.project_id == project_id,
            MonitoringTask.round_id == round_id,
        )
        .group_by(MonitoringTask.status)
    ).all()
    task_counts = {
        (status.value if hasattr(status, "value") else str(status)): int(count)
        for status, count in counts_rows
    }
    total_tasks = sum(task_counts.values())
    existing = db.scalar(
        select(StatSnapshot).where(
            StatSnapshot.project_id == project_id,
            StatSnapshot.round_id == round_id,
        )
    )
    # 已完成的轮次直接复用快照；即使历史数据里残留失败任务，也保持完成动作幂等。
    if round_row.status == RoundStatus.COMPLETED:
        if existing is None:
            raise ConflictError("轮次已完成但缺少统计快照", code="round_snapshot_missing")
        return round_row, existing, task_counts
    if total_tasks == 0:
        raise ConflictError("轮次还没有任务，不能完成", code="round_no_tasks")

    unfinished = task_counts.get(TaskStatus.PENDING.value, 0) + task_counts.get(
        TaskStatus.RUNNING.value, 0
    )
    if unfinished:
        raise ConflictError(
            f"轮次还有 {unfinished} 个未完成任务，不能完成", code="round_tasks_unfinished"
        )
    done = task_counts.get(TaskStatus.DONE.value, 0)
    failed = task_counts.get(TaskStatus.FAILED.value, 0)
    unsettled = total_tasks - done - failed
    if unsettled:
        blocked_parts = [
            f"{label} {task_counts.get(key, 0)}"
            for key, label in (
                (TaskStatus.UNCERTAIN.value, "不确定"),
                (TaskStatus.CANCELLED.value, "已取消"),
            )
            if task_counts.get(key, 0)
        ]
        detail = "、".join(blocked_parts) or f"非成功/失败状态 {unsettled}"
        raise ConflictError(
            f"轮次有 {unsettled} 个任务既未成功也未明确失败（{detail}），请先处理后再完成",
            code="round_tasks_not_succeeded",
        )

    if round_row.status != RoundStatus.RUNNING:
        raise ConflictError("轮次未开始或已关闭，不能完成", code="round_not_running")

    # 快照 scope 内记录 completed 状态，再冻结；失败时整个事务回滚，不会留下半成品。
    round_row.status = ensure_round_transition(round_row.status, RoundStatus.COMPLETED)
    snapshot = existing or create_round_snapshot(db, project_id, round_id, actor_id)
    return round_row, snapshot, task_counts
