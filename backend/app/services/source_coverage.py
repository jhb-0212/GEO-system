"""M1 引用源覆盖：这个品类里 AI 到底引用哪些站点，我们在其中占几个。

边界（改代码前先看）：

1. **品类 = 当前项目的题库**。同一个项目的问题集视为同一品类，不做跨项目品类合并。
2. **只认已复核引用**。未复核引用会让"覆盖率"忽高忽低，且无法对外解释；与指标字典里
   信源覆盖的口径保持一致（`review_status = manual_confirmed`）。
3. **覆盖 = 自有域名命中数 / Top N 域名数**，分母固定为 Top N（默认 20），不拿全网域名
   当分母——小站长尾会把覆盖率稀释成 0.4%，对外没有解释力。
4. **缺口 = 竞品被引而我们没发过的站**。判定要同时看：该域名有竞品引用、我们没有任何
   发布回执落在该域名、且不是自有域名。
"""

import uuid
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    BrandProfile,
    Channel,
    Competitor,
    MonitoringCitation,
    MonitoringCompetitorMention,
    MonitoringSample,
    PublishReceipt,
    PublishTask,
)
from app.models.enums import CitationReviewStatus, SourceCategory
from app.services.source_tiers import classify
from app.services.time_windows import project_calendar_window

CONFIRMED = CitationReviewStatus.MANUAL_CONFIRMED
VALID_STATUSES = ("hit", "miss")


def _host(url: str | None) -> str:
    if not url:
        return ""
    try:
        netloc = (urlparse(url).netloc or "").lower()
    except ValueError:
        return ""
    return netloc[4:] if netloc.startswith("www.") else netloc


def _normalize_domain(domain: str | None) -> str:
    value = (domain or "").strip().lower()
    return value[4:] if value.startswith("www.") else value


def _same_family(left: str, right: str) -> bool:
    """子域与主域视为同一站：zhuanlan.zhihu.com 的发布回执应算在 zhihu.com 上。"""
    if not left or not right:
        return False
    if left == right:
        return True
    return left.endswith(f".{right}") or right.endswith(f".{left}")


def source_coverage(
    db: Session,
    project_id: uuid.UUID,
    *,
    days: int = 90,
    limit: int = 20,
    now: datetime | None = None,
) -> dict:
    start_date, end_date, start_at = project_calendar_window(db, project_id, days, now=now)

    valid_ids = db.scalars(
        select(MonitoringSample.id).where(
            MonitoringSample.project_id == project_id,
            MonitoringSample.status.in_(VALID_STATUSES),
            MonitoringSample.sampled_at >= start_at,
        )
    ).all()

    rows = db.execute(
        select(
            MonitoringCitation.domain,
            func.count(MonitoringCitation.id),
            func.count(func.distinct(MonitoringCitation.sample_id)),
            func.count(MonitoringCitation.id).filter(MonitoringCitation.competitor_id.isnot(None)),
            func.max(MonitoringCitation.source_category),
        )
        .select_from(MonitoringCitation)
        .where(
            MonitoringCitation.project_id == project_id,
            MonitoringCitation.sample_id.in_(valid_ids),
            MonitoringCitation.review_status == CONFIRMED,
        )
        .group_by(MonitoringCitation.domain)
        .order_by(func.count(MonitoringCitation.id).desc(), MonitoringCitation.domain)
        .limit(limit)
    ).all()

    # 竞品名字：按域名聚合，供缺口行直接展示"谁在这个站被引用"
    competitor_rows = db.execute(
        select(MonitoringCitation.domain, Competitor.name)
        .select_from(MonitoringCitation)
        .join(Competitor, Competitor.id == MonitoringCitation.competitor_id)
        .where(
            MonitoringCitation.project_id == project_id,
            MonitoringCitation.sample_id.in_(valid_ids),
            MonitoringCitation.review_status == CONFIRMED,
        )
        .distinct()
    ).all()
    competitor_names: dict[str, list[str]] = {}
    for domain, name in competitor_rows:
        competitor_names.setdefault(_normalize_domain(domain), []).append(name)

    # 我方发布：按回执 URL 的主机计数，用于判断"这个站我们到底发过没有"
    receipt_rows = db.execute(
        select(PublishReceipt.published_url)
        .select_from(PublishReceipt)
        .join(PublishTask, PublishReceipt.task_id == PublishTask.id)
        .where(PublishTask.project_id == project_id)
    ).all()
    publication_counts: dict[str, int] = {}
    for (url,) in receipt_rows:
        host = _host(url)
        if host:
            publication_counts[host] = publication_counts.get(host, 0) + 1

    brand_domains = db.scalar(
        select(BrandProfile.owned_domains).where(BrandProfile.project_id == project_id)
    ) or []
    owned = {_normalize_domain(item) for item in brand_domains}
    channel_rows = db.execute(
        select(Channel.primary_domain, Channel.name).where(Channel.project_id == project_id)
    ).all()
    channel_by_domain = {
        _normalize_domain(primary): name for primary, name in channel_rows if primary
    }

    domains = []
    for domain, citations, samples, competitor_citations, source_category in rows:
        key = _normalize_domain(domain)
        is_brand_owned = any(_same_family(key, owned_item) for owned_item in owned) or (
            (source_category or "") == SourceCategory.BRAND_OWNED.value
        )
        publications = sum(
            count for host, count in publication_counts.items() if _same_family(host, key)
        )
        tier = classify(key, source_category=source_category, owned_domains=owned)
        domains.append({
            "domain": domain or "",
            "citations": int(citations or 0),
            "samples": int(samples or 0),
            "competitor_citations": int(competitor_citations or 0),
            "competitor_names": sorted(competitor_names.get(key, [])),
            "source_category": source_category or SourceCategory.UNKNOWN.value,
            "owned_by_us": is_brand_owned,
            "our_publications": publications,
            "tier": tier["tier"],
            "tier_label": tier["tier_label"],
            "tier_rule": tier["tier_rule"],
            "tier_reason": tier["tier_reason"],
            "channel_name": next(
                (name for channel_domain, name in channel_by_domain.items() if _same_family(key, channel_domain)),
                None,
            ),
        })

    top_domains = len(domains)
    owned_in_top = sum(1 for row in domains if row["owned_by_us"])
    covered_in_top = sum(1 for row in domains if row["owned_by_us"] or row["our_publications"] > 0)
    gaps = [
        {
            "domain": row["domain"],
            "competitor_citations": row["competitor_citations"],
            "competitor_names": row["competitor_names"],
        }
        for row in domains
        if row["competitor_citations"] > 0 and not row["owned_by_us"] and row["our_publications"] == 0
    ]

    total_citations = sum(row["citations"] for row in domains)
    return {
        "days": days,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "scope": {
            "valid_samples": len(valid_ids),
            "reviewed_citations": total_citations,
            "reviewed_domains": top_domains,
            "top_n": limit,
        },
        "coverage": {
            "top_domains": top_domains,
            "owned_domains": owned_in_top,
            "owned_rate": (round(owned_in_top / top_domains, 4) if top_domains else None),
            "covered_domains": covered_in_top,
            "covered_rate": (round(covered_in_top / top_domains, 4) if top_domains else None),
        },
        "domains": domains,
        "gaps": gaps[:10],
        "notes": [
            "分母固定为 Top N 已复核引用域名，不是全网域名；长尾站会稀释覆盖率。",
            "覆盖 = 自有域名命中 或 有发布回执落在该域名；只算已复核（manual_confirmed）引用。",
            "缺口 = 竞品在该站被引用、我们没有任何回执落在该站、且不是自有域名。",
        ],
    }
