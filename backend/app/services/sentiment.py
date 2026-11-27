"""情绪原文统计：三档计数 + 原文列表（按可信度排序）。

边界：
- 原文一律回读 `monitoring_citations`（只取人工复核通过），不存副本；
- 情绪结论只来自人工标注，系统不自动给正负判断；
- 可信度是「来源类别」的排序权重，用于决定阅读顺序，不等于内容质量评级。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import MonitoringCitation, SentimentLabel
from app.models.enums import CitationReviewStatus, SentimentPolarity, SourceCategory
from app.services.sentiment_sampling import citation_consensus

CONFIRMED = CitationReviewStatus.MANUAL_CONFIRMED
DECIDED_STATES = {polarity.value for polarity in SentimentPolarity}

# 可信度只是排序权重：官方 > 自有/院校/媒体 > 参考/内容平台 > 竞品 > 社交/电商 > 未知
CREDIBILITY: dict[str, tuple[int, str]] = {
    SourceCategory.GOVERNMENT_INSTITUTION.value: (5, "官方机构"),
    SourceCategory.BRAND_OWNED.value: (5, "品牌自有"),
    SourceCategory.EDUCATION_INSTITUTION.value: (4, "院校/教育机构"),
    SourceCategory.NEWS_MEDIA.value: (4, "新闻媒体"),
    SourceCategory.INDUSTRY_MEDIA.value: (4, "行业媒体"),
    SourceCategory.REFERENCE.value: (3, "参考资料"),
    SourceCategory.CONTENT_PLATFORM.value: (3, "内容平台"),
    SourceCategory.COMPETITOR_OWNED.value: (2, "竞品自有"),
    SourceCategory.SOCIAL_COMMUNITY.value: (1, "社交/UGC"),
    SourceCategory.ECOMMERCE.value: (1, "电商"),
    SourceCategory.OTHER.value: (0, "其他"),
    SourceCategory.UNKNOWN.value: (0, "未识别"),
}


def credibility_of(source_category: str | None) -> tuple[int, str]:
    return CREDIBILITY.get((source_category or "").strip(), (0, "未识别"))


def _confirmed_citations(project_id: uuid.UUID):
    return select(MonitoringCitation).where(
        MonitoringCitation.project_id == project_id,
        MonitoringCitation.review_status == CONFIRMED,
    )


def summary(db: Session, project_id: uuid.UUID) -> dict:
    total = int(db.scalar(select(func.count()).select_from(_confirmed_citations(project_id).subquery())) or 0)
    citation_ids = list(db.scalars(_confirmed_citations(project_id).with_only_columns(MonitoringCitation.id)))
    states = citation_consensus(db, project_id, citation_ids)

    counts = {polarity.value: 0 for polarity in SentimentPolarity}
    pending_second = 0
    disputed = 0
    unlabeled = 0
    for citation_id in citation_ids:
        state = (states.get(citation_id) or {}).get("state", "unlabeled")
        if state == "unlabeled":
            unlabeled += 1
        elif state == "pending_second":
            pending_second += 1
        elif state == "disputed":
            disputed += 1
        elif state in counts:
            counts[state] += 1

    consensus_total = sum(counts.values())
    labeled = total - unlabeled
    return {
        "total_reviewed_citations": total,
        "labeled": labeled,
        "unlabeled": unlabeled,
        "pending_second": pending_second,
        "disputed": disputed,
        "consensus_total": consensus_total,
        "counts": counts,
        # 标注覆盖率是操作进度，共识覆盖率才是可外推的结论分母；两者不能混用。
        "coverage": round(labeled / total, 4) if total else None,
        "consensus_coverage": round(consensus_total / total, 4) if total else None,
        "generated_at": datetime.now(timezone.utc),
    }


def _consensus_fields(state_info: dict | None) -> dict:
    """列表只展示共识结果；单人/分歧不把任何一方的判断当成最终结论。"""
    state_info = state_info or {}
    state = state_info.get("state", "unlabeled")
    labels = state_info.get("labels") or []
    decided = state in DECIDED_STATES
    if not decided:
        return {
            "polarity": None,
            "note": None,
            "grade": None,
            "labeled_at": None,
            "state": state,
            "label_count": len(labels),
        }
    notes = {label.get("note") for label in labels}
    grades = {label.get("grade") for label in labels}
    return {
        "polarity": state,
        # 两人的备注/档内等级完全一致才展示；否则只展示共识档位，不挑其中一人的原文。
        "note": next(iter(notes)) if len(notes) == 1 else None,
        "grade": next(iter(grades)) if len(grades) == 1 else None,
        "labeled_at": max((label.get("labeled_at") or "" for label in labels), default="") or None,
        "state": state,
        "label_count": len(labels),
    }


def items(
    db: Session,
    project_id: uuid.UUID,
    *,
    polarity: str | None = None,
    sort: str = "credibility",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    citations = list(db.scalars(_confirmed_citations(project_id)))
    states = citation_consensus(db, project_id, [citation.id for citation in citations])

    rendered = []
    for citation in citations:
        fields = _consensus_fields(states.get(citation.id))
        rendered.append(
            {
                "citation_id": str(citation.id),
                "title": citation.title,
                "excerpt": (citation.snippet or "").strip() or None,
                "url": citation.raw_url,
                "domain": citation.domain,
                "source_category": citation.source_category,
                "page_type": citation.page_type,
                "published_at": citation.published_at,
                **fields,
                "credibility_score": credibility_of(citation.source_category)[0],
                "credibility_tier": credibility_of(citation.source_category)[1],
            }
        )

    if polarity:
        rendered = [item for item in rendered if item["state"] == polarity]

    if sort == "recent":
        rendered.sort(key=lambda item: (item["published_at"] or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    else:
        rendered.sort(
            key=lambda item: (
                item["credibility_score"],
                item["published_at"] or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )

    total = len(rendered)
    start = max(0, (page - 1) * page_size)
    return {
        "data": rendered[start : start + page_size],
        "meta": {"page": page, "page_size": page_size, "total": total},
    }


def label_citation(
    db: Session,
    project_id: uuid.UUID,
    *,
    citation_id: uuid.UUID,
    polarity: SentimentPolarity,
    grade: str | None,
    note: str | None,
    actor_id: uuid.UUID,
) -> dict:
    # 同一人同一引用只留一条；不同标注人各写各的（双人盲评要用）
    row = db.scalar(
        select(SentimentLabel).where(
            SentimentLabel.project_id == project_id,
            SentimentLabel.citation_id == citation_id,
            SentimentLabel.labeled_by == actor_id,
        )
    )
    if row is None:
        row = SentimentLabel(project_id=project_id, citation_id=citation_id)
        db.add(row)
    row.polarity = polarity
    row.grade = grade
    row.note = note
    row.labeled_by = actor_id
    row.labeled_at = datetime.now(timezone.utc)
    db.flush()
    return {
        "citation_id": str(citation_id),
        "polarity": row.polarity.value,
        "grade": row.grade,
        "note": row.note,
        "labeled_at": row.labeled_at,
    }
