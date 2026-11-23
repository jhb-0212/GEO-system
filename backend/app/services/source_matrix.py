"""信源 × 内容形态矩阵：同一个站上，AI 引用的是哪类页面。

为什么单做这张表：覆盖率只回答「该投哪个站」，分级只回答「该投到哪一级」。真实投放时
还要回答第三个问题——「这个站上应该发长文、榜单、问答还是视频」。这张表就把
`monitoring_citations.page_type` 按站点交叉出来，给的是**历史被引形态分布**，不是推荐算法。

边界：

1. **只算已复核引用**，与覆盖/分级同口径，样本窗口一致（默认 90 天）。
2. **形态是事实分布，不是推荐**：某站 70% 被引是榜单，只说明这个站上榜单页更容易被引用，
   不推导"你应该发 7 条榜单"。要发几条由投放排期决定。
3. **同站折叠**：子域折回主域，多页只影响条数，不影响站点身份。
4. **不做合成分**：不给「形态匹配度」之类评分，只给条数与份额。
"""

import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BrandProfile, MonitoringCitation, MonitoringSample, PublishReceipt, PublishTask
from app.models.enums import CitationPageType, CitationReviewStatus, SourceCategory
from app.services.source_tiers import TIERS, classify, family_key

CONFIRMED = CitationReviewStatus.MANUAL_CONFIRMED
VALID_STATUSES = ("hit", "miss")

from app.services.industry_presets import default_terms, project_industry_config


def page_form_labels(config: dict | None = None) -> dict[str, str]:
    labels = (config or {}).get("labels", {}).get("page_forms")
    if labels:
        return dict(labels)
    return dict(default_terms("labels.page_forms", {}) or {})


FORM_LABELS: dict[str, str] = page_form_labels()


def form_label(form: str | None, labels: dict[str, str] | None = None) -> str:
    table = labels or FORM_LABELS
    return table.get(form or "", form or table.get("other", ""))


def _normalize_domain(domain: str | None) -> str:
    value = (domain or "").strip().lower()
    return value[4:] if value.startswith("www.") else value


def _host(url: str | None) -> str:
    if not url:
        return ""
    try:
        return _normalize_domain(urlparse(url).netloc or "")
    except ValueError:
        return ""


def _family(host: str, domain: str) -> bool:
    return bool(host and domain) and (host == domain or host.endswith(f".{domain}") or domain.endswith(f".{host}"))


def source_matrix(
    db: Session,
    project_id: uuid.UUID,
    *,
    days: int = 90,
    limit: int = 20,
    tiers: list[str] | None = None,
    now: datetime | None = None,
) -> dict:
    moment = now or datetime.now(UTC)
    labels = page_form_labels(project_industry_config(db, project_id))
    start_at = moment - timedelta(days=days)
    wanted_tiers = {tier.strip().upper() for tier in (tiers or ["T0", "T1", "T2"]) if tier.strip()}
    invalid_tiers = sorted(tier for tier in wanted_tiers if tier not in TIERS)
    wanted_tiers = {tier for tier in wanted_tiers if tier in TIERS} or {"T1"}

    valid_ids = db.scalars(
        select(MonitoringSample.id).where(
            MonitoringSample.project_id == project_id,
            MonitoringSample.status.in_(VALID_STATUSES),
            MonitoringSample.sampled_at >= start_at,
        )
    ).all()

    brand_domains = db.scalar(
        select(BrandProfile.owned_domains).where(BrandProfile.project_id == project_id)
    ) or []
    owned = [_normalize_domain(item) for item in brand_domains if item]

    receipt_rows = db.execute(
        select(PublishReceipt.published_url)
        .select_from(PublishReceipt)
        .join(PublishTask, PublishReceipt.task_id == PublishTask.id)
        .where(PublishTask.project_id == project_id)
    ).all()
    publication_hosts: set[str] = set()
    for (url,) in receipt_rows:
        host = _host(url)
        if host:
            publication_hosts.add(host)

    rows = db.execute(
        select(
            MonitoringCitation.domain,
            MonitoringCitation.page_type,
            MonitoringCitation.competitor_id,
            MonitoringCitation.sample_id,
            MonitoringCitation.source_category,
            func.count(MonitoringCitation.id),
        )
        .select_from(MonitoringCitation)
        .where(
            MonitoringCitation.project_id == project_id,
            MonitoringCitation.sample_id.in_(valid_ids),
            MonitoringCitation.review_status == CONFIRMED,
        )
        .group_by(
            MonitoringCitation.domain,
            MonitoringCitation.page_type,
            MonitoringCitation.competitor_id,
            MonitoringCitation.sample_id,
            MonitoringCitation.source_category,
        )
    ).all()

    site_buckets: dict[str, dict] = {}
    form_totals: dict[str, int] = {}
    for domain, page_type, competitor_id, sample_id, source_category, count in rows:
        key = family_key(domain)
        form = (page_type or CitationPageType.OTHER.value)
        # 兼容老数据里存的枚举名（如 "ARTICLE"）
        if form not in labels and form.upper() in {item.name for item in CitationPageType}:
            form = form.lower()
        bucket = site_buckets.setdefault(key, {
            "domain": key,
            "citations": 0,
            "samples": set(),
            "competitor_citations": 0,
            "source_category": source_category or SourceCategory.UNKNOWN.value,
            "forms": {},
        })
        bucket["citations"] += int(count or 0)
        bucket["samples"].add(sample_id)
        if competitor_id is not None:
            bucket["competitor_citations"] += int(count or 0)
        bucket["forms"][form] = bucket["forms"].get(form, 0) + int(count or 0)
        form_totals[form] = form_totals.get(form, 0) + int(count or 0)

    total_citations = sum(form_totals.values())
    domains: list[dict] = []
    for key, bucket in site_buckets.items():
        tier_info = classify(key, source_category=bucket["source_category"], owned_domains=owned)
        if tier_info["tier"] not in wanted_tiers:
            continue
        forms = sorted(
            ({"form": form, "label": form_label(form, labels), "citations": count}
             for form, count in bucket["forms"].items()),
            key=lambda item: (-item["citations"], item["form"]),
        )
        top_form = forms[0] if forms else None
        is_owned = tier_info["tier"] == "T0" and tier_info["tier_rule"] in {
            "owned_domain", "category:brand_owned",
        }
        published = any(_family(host, key) for host in publication_hosts)
        domains.append({
            "domain": bucket["domain"],
            "tier": tier_info["tier"],
            "tier_label": tier_info["tier_label"],
            "tier_rule": tier_info["tier_rule"],
            "citations": bucket["citations"],
            "forms": forms,
            "top_form": top_form["form"] if top_form else None,
            "top_form_label": top_form["label"] if top_form else None,
            "top_form_share": (round(top_form["citations"] / bucket["citations"], 4) if top_form else None),
            "competitor_citations": bucket["competitor_citations"],
            "owned_by_us": is_owned,
            "our_publications": 1 if published else 0,
            "status": "owned" if is_owned else ("covered" if published else ("gap" if bucket["competitor_citations"] else "untouched")),
        })
    domains.sort(key=lambda item: (-item["citations"], item["domain"]))

    return {
        "days": days,
        "scope": {
            "valid_samples": len(valid_ids),
            "reviewed_citations": total_citations,
            "domains_in_scope": len(domains),
            "returned_domains": min(limit, len(domains)),
            "tiers": sorted(wanted_tiers),
            "invalid_tiers": invalid_tiers,
        },
        "forms": [
            {
                "form": form,
                "label": form_label(form, labels),
                "citations": count,
                "citation_share": (round(count / total_citations, 4) if total_citations else None),
            }
            for form, count in sorted(form_totals.items(), key=lambda item: (-item[1], item[0]))
        ],
        "domains": domains[:limit],
        "notes": [
            "只统计已复核（manual_confirmed）引用，窗口与覆盖/分级一致。",
            "形态分布是历史被引事实，不是投放推荐：份额高不等于该按同等比例铺量。",
            "同站折叠后，子域与多页只累加条数，不重复算站点。",
            "「已覆盖」= 自有域名或有发布回执落在该站；「缺口」= 只有竞品被引、我们从未在该站发过。",
        ],
    }
