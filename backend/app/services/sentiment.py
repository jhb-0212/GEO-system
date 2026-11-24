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

CONFIRMED = CitationReviewStatus.MANUAL_CONFIRMED

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

    # 计数按「引用条」而不是「标注人次」：两人同档只算一次，分歧单列，避免双人标注把总数翻倍。
    rows = db.execute(
        select(SentimentLabel.citation_id, SentimentLabel.polarity)
        .where(SentimentLabel.project_id == project_id)
    ).all()
    by_citation: dict[uuid.UUID, set[str]] = {}
    for citation_id, polarity in rows:
        by_citation.setdefault(citation_id, set()).add(str(polarity))
    counts = {polarity.value: 0 for polarity in SentimentPolarity}
    disputed = 0
    for polarities in by_citation.values():
        if len(polarities) == 1:
            counts[next(iter(polarities))] += 1
        else:
            disputed += 1

    distinct_labeled = len(by_citation)
    return {
        "total_reviewed_citations": total,
        "labeled": min(distinct_labeled, total),
        "unlabeled": max(0, total - distinct_labeled),
        "disputed": disputed,
        "counts": counts,
        "coverage": round(distinct_labeled / total, 4) if total else None,
        "generated_at": datetime.now(timezone.utc),
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
    citations = _confirmed_citations(project_id).subquery()
    # 一条引用可能有多个标注人；列表只展示一条代表记录，避免 join 把列表分页撑大。
    label_scope = (
        select(
            SentimentLabel.citation_id,
            SentimentLabel.polarity,
            SentimentLabel.note,
            SentimentLabel.grade,
            SentimentLabel.labeled_at,
        )
        .where(SentimentLabel.project_id == project_id)
        .distinct(SentimentLabel.citation_id)
        .order_by(SentimentLabel.citation_id)
        .subquery()
    )

    stmt = (
        select(
            citations.c.id,
            citations.c.title,
            citations.c.snippet,
            citations.c.raw_url,
            citations.c.domain,
            citations.c.source_category,
            citations.c.page_type,
            citations.c.published_at,
            label_scope.c.polarity,
            label_scope.c.note,
            label_scope.c.grade,
            label_scope.c.labeled_at,
        )
        .select_from(citations)
        .join(label_scope, label_scope.c.citation_id == citations.c.id, isouter=True)
    )

    if polarity == "unlabeled":
        stmt = stmt.where(label_scope.c.polarity.is_(None))
    elif polarity:
        stmt = stmt.where(label_scope.c.polarity == polarity)

    rows = db.execute(stmt).all()
    rendered = [
        {
            "citation_id": str(row.id),
            "title": row.title,
            "excerpt": (row.snippet or "").strip() or None,
            "url": row.raw_url,
            "domain": row.domain,
            "source_category": row.source_category,
            "page_type": row.page_type,
            "published_at": row.published_at,
            "polarity": row.polarity,
            "note": row.note,
            "grade": row.grade,
            "labeled_at": row.labeled_at,
            "credibility_score": credibility_of(row.source_category)[0],
            "credibility_tier": credibility_of(row.source_category)[1],
        }
        for row in rows
    ]

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
