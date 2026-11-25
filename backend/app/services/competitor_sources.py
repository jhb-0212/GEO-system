"""竞品信源质量：按竞品拆出站点档位结构，不做合成分。"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Competitor, MonitoringCitation, MonitoringSample, Project
from app.models.enums import CitationReviewStatus
from app.services.source_tiers import TIERS, classify, family_key
from app.services.time_windows import calendar_window

CONFIRMED = CitationReviewStatus.MANUAL_CONFIRMED
VALID_STATUSES = ("hit", "miss")


def _normalize_domain(value: str | None) -> str:
    value = (value or "").strip().lower()
    return value[4:] if value.startswith("www.") else value


def competitor_source_report(
    db: Session,
    project_id: uuid.UUID,
    *,
    days: int = 90,
    limit: int = 20,
    now: datetime | None = None,
) -> dict:
    project = db.get(Project, project_id)
    start_date, end_date, start_at = calendar_window(project, days, now=now)
    valid_ids = db.scalars(
        select(MonitoringSample.id).where(
            MonitoringSample.project_id == project_id,
            MonitoringSample.status.in_(VALID_STATUSES),
            MonitoringSample.sampled_at >= start_at,
        )
    ).all()
    if not valid_ids:
        return {
            "window_days": days,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "competitors": [],
            "notes": ["窗口内没有有效样本；竞品信源结构暂时为空。"],
        }

    rows = db.execute(
        select(
            Competitor.id,
            Competitor.name,
            MonitoringCitation.domain,
            MonitoringCitation.source_category,
            MonitoringCitation.sample_id,
            func.count(MonitoringCitation.id),
        )
        .select_from(MonitoringCitation)
        .join(Competitor, Competitor.id == MonitoringCitation.competitor_id)
        .where(
            MonitoringCitation.project_id == project_id,
            MonitoringCitation.sample_id.in_(valid_ids),
            MonitoringCitation.review_status == CONFIRMED,
            MonitoringCitation.competitor_id.isnot(None),
        )
        .group_by(
            Competitor.id, Competitor.name, MonitoringCitation.domain,
            MonitoringCitation.source_category, MonitoringCitation.sample_id,
        )
    ).all()

    buckets: dict[uuid.UUID, dict] = {}
    for competitor_id, name, domain, category, sample_id, count in rows:
        key = _normalize_domain(domain)
        if not key:
            continue
        bucket = buckets.setdefault(competitor_id, {
            "id": str(competitor_id), "name": name, "citations": 0, "samples": set(),
            "domains": {},
        })
        bucket["citations"] += int(count or 0)
        bucket["samples"].add(sample_id)
        domain_bucket = bucket["domains"].setdefault(key, {
            "domain": key, "citations": 0, "samples": set(),
            "categories": Counter(),
        })
        domain_bucket["citations"] += int(count or 0)
        domain_bucket["samples"].add(sample_id)
        domain_bucket["categories"][category or "unknown"] += int(count or 0)

    competitors = []
    for bucket in buckets.values():
        tier_counts = {tier: 0 for tier in TIERS}
        domains = []
        for domain, item in bucket["domains"].items():
            category = item["categories"].most_common(1)[0][0]
            tier_info = classify(family_key(domain), source_category=category, owned_domains=set())
            tier = tier_info["tier"]
            tier_counts[tier] = tier_counts.get(tier, 0) + item["citations"]
            domains.append({
                "domain": domain,
                "tier": tier,
                "tier_label": TIERS[tier]["label"],
                "tier_rule": tier_info["tier_rule"],
                "source_category": category,
                "citations": item["citations"],
                "samples": len(item["samples"]),
            })
        total = bucket["citations"] or 1
        high_quality = tier_counts.get("T0", 0) + tier_counts.get("T1", 0)
        domains.sort(key=lambda row: (-row["citations"], row["domain"]))
        competitors.append({
            "id": bucket["id"],
            "name": bucket["name"],
            "citations": bucket["citations"],
            "samples": len(bucket["samples"]),
            "domain_count": len(domains),
            "tier_counts": tier_counts,
            "tier_shares": {
                tier: round(value / total, 4) for tier, value in tier_counts.items()
            },
            "high_quality_citations": high_quality,
            "high_quality_share": round(high_quality / total, 4),
            "top_domains": domains[:limit],
        })

    competitors.sort(key=lambda row: (-row["citations"], row["name"]))
    return {
        "window_days": days,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "competitors": competitors,
        "summary": {
            "competitors": len(competitors),
            "citations": sum(row["citations"] for row in competitors),
            "competitors_with_t0_t1": sum(1 for row in competitors if row["high_quality_citations"]),
            "average_high_quality_share": (
                round(
                    sum(row["high_quality_share"] for row in competitors) / len(competitors),
                    4,
                ) if competitors else None
            ),
        },
        "notes": [
            "只算已人工确认、命中/未命中有效样本窗口内的竞品引用。",
            "T0-T3 是站点属性，不是竞品内容质量分；高权重占比 = T0+T1 引用 / 该竞品全部引用。",
            "同一域名折叠主域；具体投放仍要结合内容形态和发布成本。",
        ],
    }
