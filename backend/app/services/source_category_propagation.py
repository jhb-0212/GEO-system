"""来源类别传播：同站一次判定，整域生效。

为什么不做逐条标注：412 条已复核引用里 96% 的 `source_category` 是 unknown，
逐条点一遍永远追不上新增引用。这里只做两件已被验证的事：

1. **同站传播**：同一站点族里只要有一条被人工判过类别，就把该类别复制给同族里
   仍是 unknown/other 的行——不是新判断，只是把已有判断补齐到同站其余行。
2. **优先级队列**：没有任何已知类别的站点按「被引条数」排序输出，先把人工花在
   影响最大的站点上（一个域名判定能覆盖几十条引用）。

纪律：只写「已知来源传未知」，绝不把 unknown 反向覆盖成 other；只列候选，预览不写库。
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import CitationReviewStatus, SourceCategory
from app.models.monitoring import MonitoringCitation
from app.services.source_tiers import family_key

CONFIRMED = CitationReviewStatus.MANUAL_CONFIRMED
UNKNOWN_VALUES = {SourceCategory.UNKNOWN.value, SourceCategory.OTHER.value}
SUBDOMAIN_PREFIXES = ("www.", "m.", "wap.", "mip.", "mobile.")


def site_key(domain: str | None) -> str:
    """站点族键：先走信源分级的白名单折叠，再把常见移动子域去掉。"""
    key = family_key(domain)
    for prefix in SUBDOMAIN_PREFIXES:
        if key.startswith(prefix) and len(key) > len(prefix):
            return key[len(prefix):]
    return key


def source_category_candidates(
    db: Session,
    project_id: uuid.UUID,
    *,
    apply: bool = False,
    limit: int = 20,
) -> dict:
    rows = list(
        db.scalars(
            select(MonitoringCitation).where(
                MonitoringCitation.project_id == project_id,
                MonitoringCitation.review_status == CONFIRMED,
            )
        )
    )

    known: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    pending: dict[str, list[MonitoringCitation]] = defaultdict(list)
    for row in rows:
        key = site_key(row.domain)
        category = row.source_category.value if row.source_category else None
        if category and category not in UNKNOWN_VALUES:
            known[key][category] += 1
        else:
            pending[key].append(row)

    candidates: list[dict] = []
    for key, items in pending.items():
        votes = known.get(key)
        if not votes:
            continue
        top_category, top_count = max(votes.items(), key=lambda item: (item[1], item[0]))
        changed = 0
        if apply:
            for row in items:
                row.source_category = SourceCategory(top_category)
                changed += 1
        candidates.append(
            {
                "site": key,
                "category": top_category,
                "evidence_citations": sum(votes.values()),
                "affected_citations": len(items),
                "changed": changed,
                "sample_domains": sorted({row.domain for row in items if row.domain})[:4],
            }
        )

    if apply:
        db.commit()

    candidates.sort(key=lambda item: -item["affected_citations"])
    # 没有任何已知类别的站点：按被引条数排序，给人一个「先判谁」的清单
    unresolved = [
        {"site": key, "citations": len(items), "sample_domains": sorted({row.domain for row in items if row.domain})[:3]}
        for key, items in pending.items()
        if key not in known
    ]
    unresolved.sort(key=lambda item: -item["citations"])

    return {
        "apply": apply,
        "scope": {
            "scanned": len(rows),
            "sites_with_evidence": len(candidates),
            "affected_citations": sum(item["affected_citations"] for item in candidates),
            "changed": sum(item["changed"] for item in candidates),
            "unresolved_sites": len(unresolved),
        },
        "candidates": candidates[:limit],
        "unresolved": unresolved[:limit],
        "notes": [
            "只把同站已有的已知类别复制给 unknown/other 行；不新增判断、不反向改已知类别。",
            "优先级按影响引用条数排序：先判被引最多的站点，一次覆盖整域。",
            "unresolved 里的站点没有任何已知类别，需要人工用「未知被引信源」队列判定。",
        ],
    }
