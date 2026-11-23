"""验收契约：一页纸把「提及率 / 引用率 / 正向率 + 连续采集天数」摊开给甲方看。

三条原则：
- 三个率各自独立，不相加、不合成一个「GEO 分」；
- 分母一律是「有效回答样本数」，样本口径与 `docs/样本口径声明.md` 一致；
- 数据不够就明说：正向率为空时返回 `not_collected`，绝不用代理指标凑数。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.monitoring import MonitoringCitation, MonitoringSample
from app.models.sentiment import SentimentLabel
from app.services.stats import (
    CONFIRMED_REVIEW_STATUS,
    VALID_SAMPLE_STATUSES,
    _rate,
    _valid_sample_scope,
    overview,
)

PROJECT_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_TARGET_STREAK = 30


def _valid_dates(
    db: Session, project_id: uuid.UUID, start_at: datetime, end_at: datetime
) -> set[str]:
    """有效样本按项目时区落到「哪一天」，用于算连续采集。"""
    samples = db.scalars(
        _valid_sample_scope(project_id, start_at=start_at, end_at=end_at)
    ).all()
    return {
        sample.sampled_at.astimezone(PROJECT_TZ).date().isoformat()
        for sample in samples
        if sample.sampled_at is not None
    }


def acceptance_contract(
    db: Session,
    project_id: uuid.UUID,
    *,
    days: int = 90,
    target_streak: int = DEFAULT_TARGET_STREAK,
    now: datetime | None = None,
) -> dict:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    start_at = now - timedelta(days=days)
    # 提及率/引用率直接走 overview，同一分母同一口径，避免两套数字
    base = overview(db, project_id, start_at=start_at, end_at=now)
    valid_answers = int(base["valid_answers"])
    mentioned = int(base["brand_mentioned_answers"])
    cited = int(base["citation_answers"])

    # 正向率：只认人工情感标注，标签挂在引用上
    label_rows = db.execute(
        select(SentimentLabel.polarity, func.count())
        .join(MonitoringCitation, MonitoringCitation.id == SentimentLabel.citation_id)
        .join(MonitoringSample, MonitoringSample.id == MonitoringCitation.sample_id)
        .where(
            SentimentLabel.project_id == project_id,
            MonitoringCitation.project_id == project_id,
            MonitoringCitation.review_status == CONFIRMED_REVIEW_STATUS,
            MonitoringSample.status.in_(VALID_SAMPLE_STATUSES),
            MonitoringSample.sampled_at >= start_at,
            MonitoringSample.sampled_at <= now,
        )
        .group_by(SentimentLabel.polarity)
    ).all()
    labeled_total = sum(int(count) for _, count in label_rows)
    positive = sum(
        int(count)
        for polarity, count in label_rows
        if getattr(polarity, "value", polarity) == "positive"
    )

    # 连续采集天数：从今天往回走，遇到没有有效样本的一天就停
    dates = _valid_dates(
        db,
        project_id,
        start_at=min(start_at, now - timedelta(days=max(days, target_streak + 7))),
        end_at=now + timedelta(days=1),
    )
    today = now.astimezone(PROJECT_TZ).date()
    streak = 0
    cursor = today
    while cursor.isoformat() in dates:
        streak += 1
        cursor = cursor - timedelta(days=1)

    rates = {
        "mention_rate": base["brand_mention_rate"],
        "citation_rate": base["citation_rate"],
        "positive_rate": _rate(positive, labeled_total),
    }
    missing = [name for name, value in rates.items() if value is None]
    return {
        "window_days": days,
        "start_at": start_at.isoformat(),
        "generated_at": now.isoformat(),
        "valid_answers": valid_answers,
        "rates": rates,
        "numerators": {
            "mentioned": mentioned,
            "cited": cited,
            "positive": positive,
            "labeled": labeled_total,
        },
        "streak": {
            "days": streak,
            "target": target_streak,
            "ok": streak >= target_streak,
            "last_date": max(dates) if dates else None,
        },
        "ready": {
            "rates_present": not missing,
            "missing": missing,
            "streak_ok": streak >= target_streak,
            "contract_ok": not missing and streak >= target_streak,
        },
        "definitions": [
            f"提及率 = 品牌被提及的有效回答 / 有效回答（近 {days} 天）。",
            f"引用率 = 有「品牌相关且人工确认」引用的有效回答 / 有效回答（近 {days} 天）。",
            "正向率 = 正向情感标注 / 已标注引用；未标注时返回空值并标 not_collected。",
            f"连续采集 = 从今天往回连续有有效样本的天数，目标 {target_streak} 天。",
            "三个率不相加、不合成综合分；数据不足显示空值，不填 0%。",
        ],
        "notes": [
            "有效回答：成功/命中且可解析的样本，失败与无回答面不计入分母。",
            "正向率依赖人工情感标注；未标注即为空，不启用任何代理口径。",
        ],
    }
