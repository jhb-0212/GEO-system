"""渠道引用明细的读取口径。

两条链路必须分清楚，混起来就会把「AI 引用了平台上的任意文章」算成「我们发的稿生效了」：

1. **渠道归因**（`channel_citation_statement`）：只认 `MonitoringCitation.channel_id`
   指向该渠道的引用 —— 这是发布回执 URL 命中的引用；
2. **域名观测**（`observed_statement`）：人工确认的引用只要落在渠道主域名/别名上就算，
   仅作信源层补充，**不写 channel_id、不进 channel_count**。

本模块只做读：摘要计数、去重后的页面/引擎/题目集合、分页明细。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    AiEngine,
    AiEngineEntry,
    Channel,
    ChannelAlias,
    MonitoringCitation,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
)

from app.services.excerpts import excerpt

# 页面 / 引擎 / 题目集合的上限：去重集合只用于筛选器，不跟着引用行数放大。
DISTINCT_LIMIT = 500


def answer_excerpt(value: str | None, limit: int = 200) -> str | None:
    """回答摘要；长度口径由调用方决定（渠道详情截 200 字）。"""
    return excerpt(value, limit)


# 两条链路列的列顺序必须一致，`citation_payload` 按位置解包。
def _base_statement():
    return select(
        MonitoringCitation.id,
        MonitoringCitation.sample_id,
        MonitoringCitation.raw_url,
        MonitoringCitation.normalized_url,
        MonitoringCitation.domain,
        MonitoringCitation.title,
        MonitoringCitation.site_name,
        MonitoringCitation.snippet,
        MonitoringCitation.published_at,
        MonitoringCitation.is_brand_related,
        MonitoringCitation.review_status,
        MonitoringSample.status,
        MonitoringSample.sampled_at,
        MonitoringSample.brand_mentioned,
        MonitoringSample.failure_code,
        MonitoringSample.raw_answer,
        MonitoringTask.id,
        AiEngine.code,
        AiEngine.name,
        Question.code,
    ).select_from(MonitoringCitation).join(
        MonitoringSample, MonitoringCitation.sample_id == MonitoringSample.id
    ).join(
        MonitoringTask, MonitoringSample.task_id == MonitoringTask.id
    ).join(
        QuestionVersion, MonitoringTask.question_version_id == QuestionVersion.id
    ).join(
        Question, QuestionVersion.question_id == Question.id
    ).join(
        AiEngineEntry, MonitoringTask.engine_entry_id == AiEngineEntry.id
    ).join(
        AiEngine, AiEngineEntry.engine_id == AiEngine.id
    )


def channel_citation_statement(channel_id: uuid.UUID, project_id: uuid.UUID):
    """渠道归因明细的基础联表语句；调用方只改列、排序与分页。"""
    return _base_statement().where(
        MonitoringCitation.channel_id == channel_id,
        MonitoringCitation.project_id == project_id,
        MonitoringSample.project_id == project_id,
        MonitoringTask.project_id == project_id,
        Question.project_id == project_id,
    )


def channel_domains(db: Session, channel: Channel) -> list[str]:
    """渠道主域名 + 别名，统一小写；只用于「域名观测」，不用于渠道效果归因。"""
    values = [channel.primary_domain] if channel.primary_domain else []
    values.extend(
        db.scalars(
            select(ChannelAlias.domain).where(
                ChannelAlias.project_id == channel.project_id,
                ChannelAlias.channel_id == channel.id,
            )
        ).all()
    )
    domains: list[str] = []
    for value in values:
        normalized = (value or "").strip().casefold().strip(".")
        if normalized.startswith("www."):
            normalized = normalized[4:]
        if normalized and normalized not in domains:
            domains.append(normalized)
    return domains


def observed_statement(project_id: uuid.UUID, domains: list[str]):
    """域名观测明细：人工确认引用命中渠道主域名/别名。管道为空返回 None。"""
    if not domains:
        return None
    domain_conditions = []
    for domain in domains:
        domain_conditions.append(MonitoringCitation.domain == domain)
        domain_conditions.append(MonitoringCitation.domain.like(f"%.{domain}"))
    return _base_statement().where(
        MonitoringCitation.project_id == project_id,
        MonitoringCitation.review_status == "manual_confirmed",
        MonitoringSample.project_id == project_id,
        MonitoringTask.project_id == project_id,
        Question.project_id == project_id,
        or_(*domain_conditions),
    )


def citation_payload(row) -> dict[str, Any]:
    (
        citation_id,
        sample_id,
        raw_url,
        normalized_url,
        domain,
        title,
        site_name,
        snippet,
        published_at,
        is_brand_related,
        review_status,
        sample_status,
        sampled_at,
        brand_mentioned,
        failure_code,
        raw_answer,
        task_id,
        engine_code,
        engine_name,
        question_code,
    ) = row
    return {
        "citation_id": str(citation_id),
        "sample_id": str(sample_id),
        "task_id": str(task_id),
        "engine_code": engine_code,
        "engine_name": engine_name,
        "question_code": question_code,
        "sample_status": str(sample_status),
        "sampled_at": sampled_at,
        "raw_url": raw_url,
        "normalized_url": normalized_url,
        "domain": domain,
        "title": title,
        "site_name": site_name,
        "snippet": snippet,
        "published_at": published_at,
        "is_brand_related": is_brand_related,
        "review_status": str(review_status),
        "brand_mentioned": brand_mentioned,
        "failure_code": str(failure_code) if failure_code else None,
        "answer_excerpt": answer_excerpt(raw_answer),
    }


@dataclass
class CitationDigest:
    """一段引用管道的四件事：计数、去重集合、时间跨度、分页明细。"""

    citation_count: int = 0
    sample_count: int = 0
    page_count: int = 0
    first_sampled_at: Any = None
    last_sampled_at: Any = None
    page_urls: list[str] = field(default_factory=list)
    engine_codes: list[str] = field(default_factory=list)
    question_codes: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)


def digest(
    db: Session,
    statement,
    *,
    page: int = 1,
    page_size: int = 20,
    distinct_limit: int = DISTINCT_LIMIT,
) -> CitationDigest:
    """对一条引用管道做一次完整读取。

    `statement` 是 `channel_citation_statement` / `observed_statement` 的产物，
    两者列一致，所以这里可以统一处理；`page_size=None` 表示不取明细（观测侧只要前 20 条）。
    """
    summary = db.execute(
        statement.with_only_columns(
            func.count().label("citation_count"),
            func.count(func.distinct(MonitoringCitation.sample_id)).label("sample_count"),
            func.count(func.distinct(MonitoringCitation.normalized_url)).label("page_count"),
            func.min(MonitoringSample.sampled_at).label("first_sampled_at"),
            func.max(MonitoringSample.sampled_at).label("last_sampled_at"),
        )
    ).one()

    page_urls = [
        url
        for url in db.scalars(
            statement.with_only_columns(MonitoringCitation.normalized_url)
            .where(MonitoringCitation.normalized_url.is_not(None))
            .distinct()
            .limit(distinct_limit)
        ).all()
        if url
    ]
    code_rows = db.execute(
        statement.with_only_columns(AiEngine.code, Question.code).distinct()
    ).all()
    engine_codes = sorted({row[0] for row in code_rows})
    question_codes = sorted({row[1] for row in code_rows})

    result = CitationDigest(
        citation_count=int(summary.citation_count or 0),
        sample_count=int(summary.sample_count or 0),
        page_count=int(summary.page_count or 0),
        first_sampled_at=summary.first_sampled_at,
        last_sampled_at=summary.last_sampled_at,
        page_urls=sorted(page_urls),
        engine_codes=engine_codes,
        question_codes=question_codes,
    )
    if page_size is None:
        return result

    rows: Sequence = db.execute(
        statement.order_by(
            MonitoringSample.sampled_at.desc().nullslast(), MonitoringCitation.id
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    result.citations = [citation_payload(row) for row in rows]
    return result
