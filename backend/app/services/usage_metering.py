"""消耗计量：只回答「用了多少」，不回答「该收多少钱」。

六个计量项与事实来源（与产品口径一致，改这里必须同时改口径文档）：

| 计量项 | 单位 | 事实来源 | 计法 |
|---|---|---|---|
| 采集执行 | 次 | `monitoring_execution_attempts` | 实际发出过请求的尝试；领取未发出（claimed/lease_expired）与本地限流（rate_limited）不占额度 |
| 内容生成 | 篇 | `generation_items` | `drafted` 即出稿成功；`failed` 不算 |
| 发布任务 | 条 | `publish_receipts` | 只认有回执的，避免虚报 |
| 收录检测 | 次 | `usage_events`（回抓批次） | 每次批量回抓记一条事件，数量=本次检查条数 |
| 报告导出 | 份 | `usage_events`（导出审计） | 每次导出成功记一条 |
| 线索 | 条 | `leads` | 线索入库即计 |

两条纪律：

1. **能派生的实时算**：前四项、线索直接数业务表，数字可全量重算、可点回明细；
2. **不能派生的记账本**：收录检测、报告导出没有可数的业务行，写 append-only `usage_events`，
   `(project_id, metric, source_type, source_id)` 唯一保证重跑不重复计数。

额度（`organizations.settings.quotas.consumption`）只用于提示：超出只警告，不拦截。
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AiEngine,
    AiEngineEntry,
    GenerationItem,
    Lead,
    MonitoringExecutionAttempt,
    MonitoringTask,
    Organization,
    Project,
    PublishReceipt,
    UsageEvent,
)
from app.models.enums import AttemptStatus, GenerationItemStatus, UsageMetric

# 已真正打到外部平台的尝试状态：请求发出过就要计消耗。
BILLED_ATTEMPT_STATUSES = (
    AttemptStatus.DISPATCHING,
    AttemptStatus.SUCCEEDED,
    AttemptStatus.FAILED,
    AttemptStatus.UNCERTAIN,
)

METRICS: list[dict[str, str]] = [
    {"metric": "collection", "label": "采集执行", "unit": "次", "basis": "facts",
     "source": "monitoring_execution_attempts", "note": "词×引擎×轮；领取未发出与本地限流不占额度"},
    {"metric": "generation", "label": "内容生成", "unit": "篇", "basis": "facts",
     "source": "generation_items", "note": "只算 drafted 出稿成功"},
    {"metric": "publishing", "label": "发布任务", "unit": "条", "basis": "facts",
     "source": "publish_receipts", "note": "只认有回执的"},
    {"metric": "reachability", "label": "收录检测", "unit": "次", "basis": "events",
     "source": "usage_events", "note": "一次批量回抓一条事件，数量为检查条数"},
    {"metric": "report_export", "label": "报告导出", "unit": "份", "basis": "events",
     "source": "usage_events", "note": "每次导出成功一条"},
    {"metric": "lead", "label": "线索", "unit": "条", "basis": "facts",
     "source": "leads", "note": "线索入库即计"},
]

METRIC_BY_CODE = {item["metric"]: item for item in METRICS}


def metric_definitions() -> list[dict[str, str]]:
    return [dict(item) for item in METRICS]


def _today() -> date:
    # 用量按本地自然日结算；UTC 在 00:00-08:00 会落到前一天，与库里 now() 的本地日期错位
    return date.today()


def _parse_day(value: Any, default: date) -> date:
    if value in (None, ""):
        return default
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ValueError(f"日期格式应为 YYYY-MM-DD：{value}") from exc


def resolve_range(start: Any = None, end: Any = None) -> tuple[date, date]:
    """默认最近 30 天（含今天）；end 不得早于 start。"""
    end_day = _parse_day(end, _today())
    start_day = _parse_day(start, end_day - timedelta(days=29))
    if start_day > end_day:
        raise ValueError("start 不能晚于 end")
    return start_day, end_day


def record(
    db: Session,
    *,
    project_id: uuid.UUID,
    metric: UsageMetric | str,
    quantity: int = 1,
    source_type: str,
    source_id: str,
    occurred_at: datetime | None = None,
    actor_id: uuid.UUID | None = None,
    meta: dict | None = None,
) -> bool:
    """写一条消耗事件；已存在同源事件返回 False，不重复计数。

    只 flush 不 commit：调用方在自己的事务边界里提交，避免计量失败回滚业务成功。
    """
    code = UsageMetric(metric).value if not isinstance(metric, UsageMetric) else metric.value
    if quantity <= 0:
        return False
    exists = db.scalar(
        select(UsageEvent.id).where(
            UsageEvent.project_id == project_id,
            UsageEvent.metric == code,
            UsageEvent.source_type == source_type,
            UsageEvent.source_id == source_id,
        )
    )
    if exists is not None:
        return False
    occurred = occurred_at or datetime.now(UTC)
    org_id = db.scalar(select(Project.organization_id).where(Project.id == project_id))
    db.add(
        UsageEvent(
            project_id=project_id,
            organization_id=org_id,
            metric=code,
            quantity=int(quantity),
            source_type=source_type,
            source_id=str(source_id),
            occurred_on=occurred.date(),
            occurred_at=occurred,
            actor_id=actor_id,
            meta=meta or {},
        )
    )
    db.flush()
    return True


def _project_ids(db: Session, project_ids: Iterable[uuid.UUID] | None, organization_id: uuid.UUID | None) -> list[uuid.UUID]:
    if project_ids is not None:
        return list(project_ids)
    if organization_id is None:
        raise ValueError("project_ids 与 organization_id 至少给一个")
    return list(
        db.scalars(select(Project.id).where(Project.organization_id == organization_id))
    )


def _count_rows(
    db: Session,
    model,
    project_ids: list[uuid.UUID],
    start: date,
    end: date,
    *,
    date_column=None,
    extra_where: Iterable = (),
) -> int:
    column = date_column or model.created_at
    if not project_ids:
        return 0
    stmt = select(func.count(model.id)).where(
        model.project_id.in_(project_ids),
        column >= start,
        column < (end + timedelta(days=1)),
        *extra_where,
    )
    return int(db.scalar(stmt) or 0)


def _collection_by_engine(db: Session, project_ids: list[uuid.UUID], start: date, end: date) -> list[dict[str, Any]]:
    """按引擎拆采集消耗：报价与核价都按引擎走，颗粒度必须到引擎。"""
    if not project_ids:
        return []
    stmt = (
        select(AiEngine.code, AiEngine.name, func.count(MonitoringExecutionAttempt.id))
        .select_from(MonitoringExecutionAttempt)
        .join(MonitoringTask, MonitoringExecutionAttempt.task_id == MonitoringTask.id)
        .join(AiEngineEntry, MonitoringTask.engine_entry_id == AiEngineEntry.id)
        .join(AiEngine, AiEngineEntry.engine_id == AiEngine.id)
        .where(
            MonitoringExecutionAttempt.project_id.in_(project_ids),
            MonitoringExecutionAttempt.status.in_(BILLED_ATTEMPT_STATUSES),
            MonitoringExecutionAttempt.created_at >= start,
            MonitoringExecutionAttempt.created_at < (end + timedelta(days=1)),
        )
        .group_by(AiEngine.code, AiEngine.name)
        .order_by(func.count(MonitoringExecutionAttempt.id).desc())
    )
    return [
        {"key": code, "label": name or code, "quantity": int(count)}
        for code, name, count in db.execute(stmt).all()
    ]


def _export_by_type(db: Session, project_ids: list[uuid.UUID], start: date, end: date) -> list[dict[str, Any]]:
    export_type = UsageEvent.meta["export_type"].astext
    rows = db.execute(
        select(export_type.label("export_type"), func.sum(UsageEvent.quantity))
        .where(
            UsageEvent.project_id.in_(project_ids),
            UsageEvent.metric == UsageMetric.REPORT_EXPORT.value,
            UsageEvent.occurred_on >= start,
            UsageEvent.occurred_on <= end,
        )
        .group_by(export_type)
    ).all()
    return [
        {"key": str(export_type or "export"), "label": str(export_type or "导出"), "quantity": int(total or 0)}
        for export_type, total in rows
    ]


def _event_total(db: Session, metric: UsageMetric, project_ids: list[uuid.UUID], start: date, end: date) -> int:
    if not project_ids:
        return 0
    total = db.scalar(
        select(func.sum(UsageEvent.quantity)).where(
            UsageEvent.project_id.in_(project_ids),
            UsageEvent.metric == metric.value,
            UsageEvent.occurred_on >= start,
            UsageEvent.occurred_on <= end,
        )
    )
    return int(total or 0)


def _quota_limits(db: Session, organization_id: uuid.UUID | None) -> dict[str, int]:
    if organization_id is None:
        return {}
    org = db.get(Organization, organization_id)
    if org is None or not isinstance(org.settings, dict):
        return {}
    quotas = org.settings.get("quotas") or {}
    consumption = quotas.get("consumption") or {}
    return {
        str(key): int(value)
        for key, value in consumption.items()
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
    }


def _quota_state(used: int, limit: int | None) -> dict | None:
    if limit is None:
        return None
    if used >= limit:
        return {"limit": limit, "used": used, "level": "exceeded",
                "message": f"已用 {used}/{limit}，超出额度只提示，不拦截业务"}
    if limit > 0 and used * 5 >= limit * 4:
        return {"limit": limit, "used": used, "level": "warning",
                "message": f"已用 {used}/{limit}，接近额度"}
    return None


def summarize(
    db: Session,
    start: Any = None,
    end: Any = None,
    *,
    project_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """按项目或按客户汇总六项消耗；单位不同，不做加总。"""
    start_day, end_day = resolve_range(start, end)
    if project_id is not None:
        project_ids = [project_id]
        org_id = db.scalar(select(Project.organization_id).where(Project.id == project_id))
    else:
        project_ids = _project_ids(db, None, organization_id)
        org_id = organization_id

    if project_ids:
        collection = _count_rows(
            db, MonitoringExecutionAttempt, project_ids, start_day, end_day,
            extra_where=(MonitoringExecutionAttempt.status.in_(BILLED_ATTEMPT_STATUSES),),
        )
        generation = _count_rows(
            db, GenerationItem, project_ids, start_day, end_day,
            extra_where=(GenerationItem.status == GenerationItemStatus.DRAFTED,),
        )
        publishing = _count_rows(
            db, PublishReceipt, project_ids, start_day, end_day, date_column=PublishReceipt.received_at,
        )
        leads = _count_rows(db, Lead, project_ids, start_day, end_day)
    else:
        collection = generation = publishing = leads = 0
    reachability = _event_total(db, UsageMetric.REACHABILITY, project_ids, start_day, end_day)
    report_export = _event_total(db, UsageMetric.REPORT_EXPORT, project_ids, start_day, end_day)

    quantities = {
        "collection": collection, "generation": generation, "publishing": publishing,
        "reachability": reachability, "report_export": report_export, "lead": leads,
    }
    details = {
        "collection": _collection_by_engine(db, project_ids, start_day, end_day),
        "report_export": _export_by_type(db, project_ids, start_day, end_day),
    }
    limits = _quota_limits(db, org_id)

    metrics: list[dict[str, Any]] = []
    for item in METRICS:
        code = item["metric"]
        used = quantities[code]
        row: dict[str, Any] = {**item, "quantity": used}
        if details.get(code):
            row["detail"] = details[code]
        quota = _quota_state(used, limits.get(code))
        if quota is not None:
            row["quota"] = quota
        metrics.append(row)

    return {
        "scope": "project" if project_id is not None else "organization",
        "project_id": str(project_id) if project_id else None,
        "organization_id": str(org_id) if org_id else None,
        "range": {"start": start_day.isoformat(), "end": end_day.isoformat()},
        "metrics": metrics,
        "alerts": [{"metric": row["metric"], **row["quota"]} for row in metrics if row.get("quota")],
        "note": "只做用量统计，不含价格、套餐与账单；额度超限只提示不拦截。",
    }


def events(
    db: Session,
    start: Any = None,
    end: Any = None,
    *,
    project_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    metric: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """账本明细：让页面上的数字能点回到具体事件。"""
    start_day, end_day = resolve_range(start, end)
    project_ids = [project_id] if project_id else _project_ids(db, None, organization_id)
    if not project_ids:
        return []
    stmt = (
        select(UsageEvent)
        .where(
            UsageEvent.project_id.in_(project_ids),
            UsageEvent.occurred_on >= start_day,
            UsageEvent.occurred_on <= end_day,
        )
        .order_by(UsageEvent.occurred_on.desc(), UsageEvent.created_at.desc())
        .limit(max(1, min(int(limit), 500)))
    )
    if metric:
        stmt = stmt.where(UsageEvent.metric == UsageMetric(metric).value)
    rows = db.scalars(stmt).all()
    return [
        {
            "id": str(row.id),
            "project_id": str(row.project_id),
            "metric": row.metric,
            "label": METRIC_BY_CODE.get(row.metric, {}).get("label", row.metric),
            "quantity": row.quantity,
            "unit": METRIC_BY_CODE.get(row.metric, {}).get("unit", ""),
            "source_type": row.source_type,
            "source_id": row.source_id,
            "occurred_on": row.occurred_on.isoformat(),
            "meta": row.meta or {},
        }
        for row in rows
    ]
