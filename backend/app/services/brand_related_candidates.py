"""品牌相关性补齐：把「这条引用是否关于品牌」的判断从空白补成可复核的候选清单。

为什么要单独一层：`citation_rate` 的分母口径是「品牌相关且人工确认」，但真实库里
412 条已确认引用只有 1 条 `is_brand_related=True`——不是没有相关内容，而是这个标记
在复核时基本没人勾。没有它，引用率与正向率都只剩个位数分母。

做法有三条纪律：
1. 只出候选，不自动定论：标题/摘要命中品牌词表才进候选，`preview` 不写库。
2. 只写 true，不写 false：判不出来就保持原值，不用默认值伪造负面结论。
3. 只动已人工复核的引用：auto 状态的行不在本层处理，避免顺带把复核口径放开。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import CitationReviewStatus
from app.models.monitoring import MonitoringCitation
from app.services.brand_profile import build_vocabulary

# 两字以内的短词（例如两字品牌简称）容易误伤，不参与候选命中；仍保留在提及率词表里。
MIN_TERM_LEN = 3


def _candidate_terms(db: Session, project_id: uuid.UUID) -> list[str]:
    vocabulary = build_vocabulary(db, project_id)
    terms = [term for term in vocabulary.mention_terms if len(term) >= MIN_TERM_LEN]
    terms += [domain for domain in vocabulary.owned_domains if domain]
    return sorted({term.strip() for term in terms if term and term.strip()})


def brand_related_candidates(
    db: Session,
    project_id: uuid.UUID,
    *,
    apply: bool = False,
    limit: int = 500,
    sample_limit: int = 20,
) -> dict:
    terms = _candidate_terms(db, project_id)
    if not terms:
        return {
            "apply": apply,
            "scope": {"scanned": 0, "candidates": 0, "changed": 0},
            "by_term": {},
            "by_domain": {},
            "examples": [],
            "notes": ["项目尚未配置品牌词表，无法生成候选。"],
        }

    rows = list(
        db.scalars(
            select(MonitoringCitation)
            .where(
                MonitoringCitation.project_id == project_id,
                MonitoringCitation.review_status == CitationReviewStatus.MANUAL_CONFIRMED,
                MonitoringCitation.is_brand_related.is_not(True),
            )
            .order_by(MonitoringCitation.created_at.asc())
            .limit(limit)
        )
    )

    candidates: list[tuple[MonitoringCitation, list[str]]] = []
    by_term: dict[str, int] = {}
    for row in rows:
        haystack = " ".join(
            part for part in (row.title, row.snippet, row.domain, row.raw_url) if part
        ).lower()
        matched = [term for term in terms if term.lower() in haystack]
        if not matched:
            continue
        candidates.append((row, matched))
        for term in matched:
            by_term[term] = by_term.get(term, 0) + 1

    by_domain: dict[str, int] = {}
    examples: list[dict] = []
    changed = 0
    for row, matched in candidates:
        by_domain[row.domain] = by_domain.get(row.domain, 0) + 1
        if apply:
            row.is_brand_related = True
            changed += 1
        if len(examples) < sample_limit:
            examples.append(
                {
                    "citation_id": str(row.id),
                    "raw_url": row.raw_url,
                    "domain": row.domain,
                    "title": row.title,
                    "page_type": row.page_type.value if row.page_type else None,
                    "matched_terms": matched,
                    "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
                }
            )

    if apply:
        db.commit()

    return {
        "apply": apply,
        "scope": {"scanned": len(rows), "candidates": len(candidates), "changed": changed},
        "by_term": dict(sorted(by_term.items(), key=lambda item: -item[1])),
        "by_domain": dict(sorted(by_domain.items(), key=lambda item: -item[1])[:20]),
        "examples": examples,
        "notes": [
            "只处理人工复核通过、且当前不是「品牌相关」的引用；preview 不写库。",
            "命中依据：标题、摘要、域名或 URL 出现品牌正式名/别名/自有域名；只看事实字符串，不做语义推测。",
            "只写 true，不写 false：判不出来就保持原值。",
        ],
    }
