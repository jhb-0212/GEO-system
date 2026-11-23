"""站点证据抓取：给待人工判的域名取一份「站点自己写的自我介绍」。

判定仍由人做；这里只负责把人工本来要开浏览器才能看到的东西提前取回来：
- 站点根域首页的 `<title>` 与 `meta description`（站点自我定位，最直接的证据）；
- 一条被引页面（该站挂在我们引用里最多的那条）的标题，用来看该站被 AIGC 引用的是哪类内容。

取不到就记状态，不猜；已抓过的站点默认跳过，`refresh` 才重抓。
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import CitationReviewStatus
from app.models.monitoring import MonitoringCitation
from app.models.source_domain import SourceDomainEvidence
from app.services.page_title_backfill import fetch_title
from app.services.source_category_propagation import UNKNOWN_VALUES, site_key

CONFIRMED = CitationReviewStatus.MANUAL_CONFIRMED
THREADPOOL = 4


def _needs_review_sites(db: Session, project_id: uuid.UUID) -> dict[str, list[MonitoringCitation]]:
    rows = list(
        db.scalars(
            select(MonitoringCitation).where(
                MonitoringCitation.project_id == project_id,
                MonitoringCitation.review_status == CONFIRMED,
            )
        )
    )
    sites: dict[str, list[MonitoringCitation]] = defaultdict(list)
    known: set[str] = set()
    for row in rows:
        key = site_key(row.domain)
        sites[key].append(row)
        value = row.source_category.value if row.source_category else None
        if value and value not in UNKNOWN_VALUES:
            known.add(key)
    return {key: items for key, items in sites.items() if key not in known}


def _fetch_one(site: str, items: list[MonitoringCitation]) -> dict:
    root = fetch_title(f"https://{site}/")
    sample = max(items, key=lambda row: len(row.raw_url or ""))
    sample_result = fetch_title(sample.raw_url) if sample.raw_url else None
    if root.status == "ok" or (sample_result and sample_result.status == "ok"):
        status = "ok"
    else:
        status = root.status
    return {
        "site": site,
        "fetched_url": f"https://{site}/",
        "title": root.title,
        "description": root.snippet,
        "sample_url": sample.raw_url,
        "sample_title": sample_result.title if sample_result else None,
        "status": status,
        "detail": root.detail or (sample_result.detail if sample_result else None),
    }


def collect_domain_evidence(
    db: Session,
    project_id: uuid.UUID,
    *,
    limit: int = 0,
    refresh: bool = False,
) -> dict:
    sites = _needs_review_sites(db, project_id)
    existing = {
        row.site: row
        for row in db.scalars(
            select(SourceDomainEvidence).where(SourceDomainEvidence.project_id == project_id)
        )
    }
    targets = sorted(sites.items(), key=lambda kv: -len(kv[1]))
    if not refresh:
        targets = [(site, items) for site, items in targets if site not in existing]
    if limit:
        targets = targets[:limit]

    results: list[dict] = []
    if targets:
        with ThreadPoolExecutor(max_workers=THREADPOOL) as pool:
            futures = [pool.submit(_fetch_one, site, items) for site, items in targets]
            for future in futures:
                results.append(future.result())

    now = datetime.now(UTC)
    for payload in results:
        row = existing.get(payload["site"])
        if row is None:
            row = SourceDomainEvidence(project_id=project_id, site=payload["site"])
            db.add(row)
            existing[payload["site"]] = row
        for field in ("fetched_url", "title", "description", "sample_url", "sample_title", "status", "detail"):
            setattr(row, field, payload[field])
        row.fetched_at = now
    db.commit()

    ok = sum(1 for item in results if item["status"] == "ok")
    return {
        "fetched": len(results),
        "ok": ok,
        "failed": len(results) - ok,
        "still_missing": len(sites) - len(existing),
        "sites": [
            {"site": item["site"], "status": item["status"], "title": item["title"]}
            for item in results
        ][:50],
    }


def evidence_map(db: Session, project_id: uuid.UUID) -> dict[str, dict]:
    return {
        row.site: {
            "title": row.title,
            "description": row.description,
            "sample_title": row.sample_title,
            "status": row.status,
            "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
        }
        for row in db.scalars(
            select(SourceDomainEvidence).where(SourceDomainEvidence.project_id == project_id)
        )
    }
