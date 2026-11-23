"""B1 双轨大屏：投放侧与测量侧各看各的，中间不放合计。

为什么不合：两侧分母不同——投放侧的分母是「发布任务」，测量侧的分母是「有效样本」。
硬合成一个「整体得分」等于把两个不同统计单位相加，任何权重变化都会让历史不可比。
因此这里只输出两列事实，且每项都带自己的分子/分母；没有数据时 value 为 None。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    MonitoringCitation,
    MonitoringRound,
    MonitoringSample,
    PublishReceipt,
    PublishTask,
    PublishVisibilityCheck,
)
from app.models.enums import PublishTaskStatus, RoundStatus
from app.services.stats import (
    CONFIRMED_REVIEW_STATUS,
    _count,
    _rate,
    _valid_sample_scope,
)


def _metric(key: str, label: str, numerator: int, denominator: int, *, unit: str = "条") -> dict:
    """统一口径：分子/分母原样给出，比率只在分母非零时计算。"""
    return {
        "key": key,
        "label": label,
        "numerator": numerator,
        "denominator": denominator,
        "value": _rate(numerator, denominator) if unit == "%" else None,
        "unit": unit,
        "has_data": denominator > 0,
    }


def dispatch_track(db: Session, project_id: uuid.UUID, *, days: int = 30) -> dict:
    """投放侧：任务、回执、收录检测、闭环。分母统一是「建了多少任务」。"""
    since = datetime.now(UTC) - timedelta(days=days)
    task_total = _count(select(PublishTask).where(PublishTask.project_id == project_id), db)
    task_window = _count(
        select(PublishTask).where(
            PublishTask.project_id == project_id, PublishTask.created_at >= since
        ),
        db,
    )
    published = _count(
        select(PublishTask).where(
            PublishTask.project_id == project_id,
            PublishTask.status == PublishTaskStatus.PUBLISHED,
        ),
        db,
    )
    cancelled = _count(
        select(PublishTask).where(
            PublishTask.project_id == project_id,
            PublishTask.status == PublishTaskStatus.CANCELLED,
        ),
        db,
    )
    # 有效任务 = 没被取消的；取消的单子不该进任何比率的分母
    active = task_total - cancelled
    receipts = _count(select(PublishReceipt).where(PublishReceipt.project_id == project_id), db)
    # 检测失败（error_code 非空）不算「未收录」：它既不是命中也不是未命中，直接剔出分母
    check_scope = select(PublishVisibilityCheck).where(
        PublishVisibilityCheck.project_id == project_id,
        PublishVisibilityCheck.error_code.is_(None),
    )
    checks = _count(check_scope, db)
    indexed = _count(check_scope.where(PublishVisibilityCheck.matched.is_(True)), db)
    # 闭环必须按任务算：同一任务「既有回执、又有成功收录检测」才算走得通；
    # 用 receipts/indexed 两个总量取小值会高估（回执和收录可能不是同一批任务）。
    closed = _count(
        select(PublishTask.id)
        .join(PublishReceipt, PublishReceipt.task_id == PublishTask.id)
        .join(PublishVisibilityCheck, PublishVisibilityCheck.receipt_id == PublishReceipt.id)
        .where(
            PublishTask.project_id == project_id,
            PublishVisibilityCheck.error_code.is_(None),
            PublishVisibilityCheck.matched.is_(True),
        )
        .distinct(),
        db,
    )

    return {
        "track": "dispatch",
        "label": "投放侧",
        "window_days": days,
        "metrics": [
            _metric("tasks_total", "发布任务（累计）", task_total, task_total),
            _metric("tasks_window", f"发布任务（近 {days} 天）", task_window, task_window),
            _metric("published", "已发布任务", published, active, unit="%"),
            _metric("receipts", "已收回执", receipts, active, unit="%"),
            _metric("indexed", "收录检测通过", indexed, checks, unit="%"),
            _metric("closure", "回执 + 收录都齐的闭环", closed, active, unit="%"),
        ],
        "notes": [
            "分母是未取消的发布任务；取消任务不计入，但仍在「累计」里可见。",
            "「闭环」按回执与收录同时具备计，缺任一即不算闭环。",
        ],
    }


def measurement_track(db: Session, project_id: uuid.UUID, *, days: int = 30) -> dict:
    """测量侧：样本、提及、引用复核。分母统一是「有效样本」或「已复核引用」。"""
    since = datetime.now(UTC) - timedelta(days=days)
    rounds = _count(select(MonitoringRound).where(MonitoringRound.project_id == project_id), db)
    running = _count(
        select(MonitoringRound).where(
            MonitoringRound.project_id == project_id,
            MonitoringRound.status == RoundStatus.RUNNING,
        ),
        db,
    )
    samples = _count(select(MonitoringSample).where(MonitoringSample.project_id == project_id), db)
    valid_scope = _valid_sample_scope(project_id, start_at=since)
    valid_samples = _count(valid_scope, db)
    mentioned = _count(
        _valid_sample_scope(project_id, start_at=since).where(
            MonitoringSample.brand_mentioned.is_(True)
        ),
        db,
    )
    citations = _count(
        select(MonitoringCitation).where(MonitoringCitation.project_id == project_id), db
    )
    reviewed = _count(
        select(MonitoringCitation).where(
            MonitoringCitation.project_id == project_id,
            MonitoringCitation.review_status == CONFIRMED_REVIEW_STATUS,
        ),
        db,
    )

    return {
        "track": "measurement",
        "label": "测量侧",
        "window_days": days,
        "metrics": [
            _metric("rounds", "监测轮次（累计）", rounds, rounds),
            _metric("running", "进行中轮次", running, rounds),
            _metric("samples_total", "样本（累计）", samples, samples),
            _metric("samples_window", f"有效样本（近 {days} 天）", valid_samples, valid_samples),
            _metric("mentioned", "品牌被提及", mentioned, valid_samples, unit="%"),
            _metric("citations", "引用条数（累计）", citations, citations),
            _metric("reviewed", "已人工复核引用", reviewed, citations, unit="%"),
        ],
        "notes": [
            "提及率的分母只有近窗口内的有效样本；无样本时值为 null，不拿 0 冒充分数。",
            "引用复核率的分母是全部引用条数，人工复核不是抽样估计。",
        ],
    }


def tracks_snapshot(db: Session, project_id: uuid.UUID, *, days: int = 30) -> dict:
    return {
        "days": days,
        "disclaimer": "投放侧与测量侧分母不同，本屏不提供合并总分。",
        "tracks": [
            dispatch_track(db, project_id, days=days),
            measurement_track(db, project_id, days=days),
        ],
    }
