"""AI 引用未知域名队列：分页、计数与逐域名统计只在这里算一次。

为什么下沉到 service：
这条查询同时给了三个数字——队列总数、每个域名的引用次数、覆盖样本数。
它们和统计看板上的「信源分布」是同一类口径，如果留在 api 里各写一份 SQL，
统计页与队列页迟早对不上，而且没人能说清哪个对（`services/stats.py` 开篇已写明
口径只许有一处）。

api 层只负责鉴权、分页参数与响应包装。
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CitationSourceReview, MonitoringCitation, MonitoringSample
from app.models.enums import SourceReviewStatus

STATS_BASIS = "citation_count=引用次数，sample_count=覆盖样本数（distinct sample_id）"


def domain_stats(db: Session, project_id: uuid.UUID, domains: list[str]) -> dict:
    """逐域名的引用次数 / 覆盖样本数 / 最近采样时间。"""
    if not domains:
        return {}
    rows = db.execute(
        select(
            MonitoringCitation.domain,
            func.count().label("citation_count"),
            func.count(func.distinct(MonitoringCitation.sample_id)).label("sample_count"),
            func.max(MonitoringSample.sampled_at).label("last_sampled_at"),
        )
        .join(MonitoringSample, MonitoringCitation.sample_id == MonitoringSample.id)
        .where(
            MonitoringCitation.project_id == project_id,
            MonitoringCitation.domain.in_(domains),
        )
        .group_by(MonitoringCitation.domain)
    ).all()
    return {row.domain: row for row in rows}


def page_source_reviews(
    db: Session,
    project_id: uuid.UUID,
    *,
    status: SourceReviewStatus | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[CitationSourceReview], dict]:
    """返回 (总数, 当前页记录, 域名统计字典)。"""
    conditions = [CitationSourceReview.project_id == project_id]
    if status is not None:
        conditions.append(CitationSourceReview.status == status)
    total = int(
        db.scalar(select(func.count()).select_from(CitationSourceReview).where(*conditions)) or 0
    )
    rows = list(
        db.scalars(
            select(CitationSourceReview)
            .where(*conditions)
            .order_by(CitationSourceReview.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    stats = domain_stats(db, project_id, [row.domain for row in rows])
    return total, rows, stats
