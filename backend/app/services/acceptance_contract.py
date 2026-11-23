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
from app.models.enums import SourceCategory
from app.models.sentiment import SentimentLabel
from app.services.sentiment_sampling import MIN_REPORT, cumulative_consensus
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

    # 正向率：只认「双人同档」的共识，单人标注不算数
    consensus = cumulative_consensus(db, project_id, scope="brand_related", max_rounds=12)
    positive_rate = consensus["positive_rate"]
    consensus_total = consensus["consensus_total"]
    positive_reason = None if positive_rate is not None else (
        "insufficient_consensus" if (consensus_total or consensus.get("pending_second")) else "not_collected"
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

    # 引用来源结构：引用率涨了要说清楚涨在哪，别让软文占比藏在总数里
    cited_scope = (
        select(MonitoringCitation.source_category, func.count())
        .join(MonitoringSample, MonitoringSample.id == MonitoringCitation.sample_id)
        .where(
            MonitoringCitation.project_id == project_id,
            MonitoringCitation.review_status == CONFIRMED_REVIEW_STATUS,
            MonitoringCitation.is_brand_related.is_(True),
            MonitoringSample.status.in_(VALID_SAMPLE_STATUSES),
            MonitoringSample.sampled_at >= start_at,
            MonitoringSample.sampled_at <= now,
        )
        .group_by(MonitoringCitation.source_category)
    )
    mix_rows = db.execute(cited_scope).all()
    mix = {
        (getattr(category, "value", category) or "unknown"): int(count)
        for category, count in mix_rows
    }
    low_trust_categories = {
        SourceCategory.SOCIAL_COMMUNITY.value,
        SourceCategory.ECOMMERCE.value,
        SourceCategory.OTHER.value,
    }
    low_trust = sum(count for category, count in mix.items() if category in low_trust_categories)
    # unknown 是「来源类别没识别」，不等于低可信，单列披露
    unknown = mix.get(SourceCategory.UNKNOWN.value, 0)
    mix_total = sum(mix.values())

    rates = {
        "mention_rate": base["brand_mention_rate"],
        "citation_rate": base["citation_rate"],
        "positive_rate": positive_rate,
    }
    missing = [name for name, value in rates.items() if value is None]
    return {
        "window_days": days,
        "start_at": start_at.isoformat(),
        "generated_at": now.isoformat(),
        "valid_answers": valid_answers,
        "rates": rates,
        "positive_basis": {
            "mode": "cumulative_consensus",
            "rounds": consensus["rounds"],
            "sampled": consensus["sampled"],
            "consensus_total": consensus_total,
            "disputed": consensus["disputed"],
            "pending_second": consensus.get("pending_second", 0),
            "min_report": MIN_REPORT,
            "widened": consensus["widened"],
            "reason": positive_reason,
        },
        "cited_source_mix": {
            "by_category": mix,
            "total": mix_total,
            "low_trust_total": low_trust,
            "low_trust_share": _rate(low_trust, mix_total) if mix_total else None,
            "low_trust_categories": sorted(low_trust_categories),
            "unknown_total": unknown,
            "unknown_share": _rate(unknown, mix_total) if mix_total else None,
        },
        "numerators": {
            "mentioned": mentioned,
            "cited": cited,
            "positive": consensus["counts"].get("positive", 0),
            "labeled": consensus_total,
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
            f"正向率 = 双人同档共识里正向的条数 / 共识总条数；共识不足 {MIN_REPORT} 条不出率，单人标注不计。",
            f"连续采集 = 从今天往回连续有有效样本的天数，目标 {target_streak} 天。",
            "三个率不相加、不合成综合分；数据不足显示空值，不填 0%。",
        ],
        "notes": [
            "有效回答：成功/命中且可解析的样本，失败与无回答面不计入分母。",
            "引用来源结构：按被引页的来源类别计数；社交/UGC、电商、其他合称低可信来源，未识别单列，占比只作披露、不参与率的加减。",
            "正向率来自跨轮抽样共识池（第 1..12 轮并集），不受 90 天窗口限制；单人标注不算共识。",
        ],
    }
