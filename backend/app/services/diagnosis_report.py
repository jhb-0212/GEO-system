"""诊断报告的五个分项数字：分子 / 分母 / 样本数，只给事实不给评级。

口径源：`docs/metric-dictionary.md`。改口径先改文档，再改这里。
本模块只读，不写库、不新增快照；报告按请求现算，避免出现「冻结后口径漂移」。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import MonitoringCitation, MonitoringCompetitorMention
from app.models.enums import AnswerKind, QuestionType, SourceCategory
from app.models.monitoring import MonitoringSample
from app.services.brand_profile import build_vocabulary
from app.services.stats import (
    CONFIRMED_REVIEW_STATUS,
    _citation_scope,
    _count,
    _rate,
    _sample_scope,
    _valid_sample_scope,
)


def _dimension(
    key: str,
    label: str,
    numerator: int,
    denominator: int,
    *,
    definition: str,
    basis: str,
    extra: dict | None = None,
) -> dict:
    return {
        "key": key,
        "label": label,
        "value": _rate(numerator, denominator) if denominator else None,
        "numerator": numerator,
        "denominator": denominator,
        "unit": "%",
        "definition": definition,
        "basis": basis,
        "extra": extra or {},
        "has_data": denominator > 0,
    }


def _first_rank_count(db: Session, scope) -> int:
    """首推：位次明确为 1 的有效样本数。"""
    return _count(scope.where(MonitoringSample.brand_list_rank == 1), db)


def _competitor_outrank(db: Session, project_id: uuid.UUID, scope) -> dict:
    """竞品位次：只在品牌与竞品同时有位次的样本里比较。"""
    scope_sq = scope.subquery()
    sample_rows = db.execute(
        select(scope_sq.c.id, scope_sq.c.brand_list_rank).select_from(scope_sq)
    ).all()
    brand_ranks = {
        row.id: int(row.brand_list_rank)
        for row in sample_rows
        if row.brand_list_rank is not None
    }
    if not brand_ranks:
        return {"outrank": 0, "compared": 0, "brand_avg": None, "competitor_avg": None}

    best_rows = db.execute(
        select(
            MonitoringCompetitorMention.sample_id,
            func.min(MonitoringCompetitorMention.position),
        )
        .where(
            MonitoringCompetitorMention.project_id == project_id,
            MonitoringCompetitorMention.sample_id.in_(list(brand_ranks)),
            MonitoringCompetitorMention.position.is_not(None),
        )
        .group_by(MonitoringCompetitorMention.sample_id)
    ).all()

    compared = 0
    outrank = 0
    brand_sum = 0
    competitor_sum = 0
    for sample_id, best_position in best_rows:
        if best_position is None or sample_id not in brand_ranks:
            continue
        compared += 1
        brand_rank = brand_ranks[sample_id]
        brand_sum += brand_rank
        competitor_sum += int(best_position)
        if brand_rank <= int(best_position):
            outrank += 1

    return {
        "outrank": outrank,
        "compared": compared,
        "brand_avg": round(brand_sum / compared, 2) if compared else None,
        "competitor_avg": round(competitor_sum / compared, 2) if compared else None,
    }


def _source_coverage(db: Session, citation_scope) -> dict:
    """信源覆盖：已复核引用里，品牌自有域名占多少个去重域名。"""
    reviewed = citation_scope.where(MonitoringCitation.review_status == CONFIRMED_REVIEW_STATUS)
    reviewed_sq = reviewed.subquery()
    total_domains = int(
        db.scalar(
            select(func.count(func.distinct(reviewed_sq.c.domain))).select_from(reviewed_sq)
        )
        or 0
    )
    brand_domains = int(
        db.scalar(
            select(func.count(func.distinct(reviewed_sq.c.domain)))
            .select_from(reviewed_sq)
            .where(reviewed_sq.c.source_category == SourceCategory.BRAND_OWNED.value)
        )
        or 0
    )
    return {"total_domains": total_domains, "brand_domains": brand_domains}


def _context_quality(db: Session, project_id: uuid.UUID, citation_scope) -> dict:
    """引用上下文质量：已复核引用的标题/摘要是否出现品牌名或别名。"""
    reviewed = citation_scope.where(MonitoringCitation.review_status == CONFIRMED_REVIEW_STATUS)
    total = _count(reviewed, db)
    if total == 0:
        return {"hit": 0, "total": 0, "terms": []}

    vocabulary = build_vocabulary(db, project_id)
    terms = vocabulary.mention_terms
    if not terms:
        return {"hit": 0, "total": total, "terms": []}

    conditions = []
    for term in terms:
        conditions.append(MonitoringCitation.title.ilike(f"%{term}%"))
        conditions.append(MonitoringCitation.snippet.ilike(f"%{term}%"))
    hit = _count(reviewed.where(or_(*conditions)), db)

    reviewed_sq = reviewed.subquery()
    page_rows = db.execute(
        select(reviewed_sq.c.page_type, func.count())
        .select_from(reviewed_sq)
        .group_by(reviewed_sq.c.page_type)
        .order_by(func.count().desc())
        .limit(3)
    ).all()
    page_types = [
        {"page_type": (row[0] or "unknown"), "count": int(row[1])}
        for row in page_rows
    ]
    return {"hit": hit, "total": total, "terms": terms, "page_types": page_types}


def diagnosis_report(
    db: Session,
    project_id: uuid.UUID,
    *,
    round_id: uuid.UUID | None = None,
    engine_id: uuid.UUID | None = None,
    question_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    answer_kind: AnswerKind | None = None,
    question_type: QuestionType | str | None = None,
) -> dict:
    scope_filters = {
        "round_id": round_id,
        "engine_id": engine_id,
        "question_id": question_id,
        "start_at": start_at,
        "end_at": end_at,
        "answer_kind": answer_kind,
        "question_type": question_type,
    }

    valid_scope = _valid_sample_scope(project_id, **scope_filters)
    valid_answers = _count(valid_scope, db)

    mentioned = _count(valid_scope.where(MonitoringSample.brand_mentioned.is_(True)), db)
    first_rank = _first_rank_count(db, valid_scope)

    all_scope = _sample_scope(project_id, **scope_filters)
    all_subquery = all_scope.subquery()
    status_rows = db.execute(
        select(all_subquery.c.status, func.count()).select_from(all_subquery).group_by(all_subquery.c.status)
    ).all()
    status_counts = {str(status): int(count) for status, count in status_rows}
    excluded = {
        "failed": status_counts.get("failed", 0),
        "manual_review": status_counts.get("manual_review", 0),
        "no_answer_surface": status_counts.get("no_answer_surface", 0),
        "pending_or_running": status_counts.get("pending", 0) + status_counts.get("running", 0),
    }

    citation_scope = _citation_scope(project_id, **scope_filters)
    coverage = _source_coverage(db, citation_scope)
    context = _context_quality(db, project_id, citation_scope)
    competitor = _competitor_outrank(db, project_id, valid_scope)

    dimensions = [
        _dimension(
            "mention_rate", "提及率", mentioned, valid_answers,
            definition="点名提到品牌（正式名或别名）的有效回答占比",
            basis="monitoring_samples.brand_mentioned",
        ),
        _dimension(
            "first_rank_rate", "首推率", first_rank, valid_answers,
            definition="品牌出现在第一推荐位的有效回答占比；分母仍是全部有效回答",
            basis="monitoring_samples.brand_list_rank = 1",
        ),
        _dimension(
            "source_coverage", "信源覆盖", coverage["brand_domains"], coverage["total_domains"],
            definition="已复核引用中，品牌自有域名占全部去重信源域名的比例",
            basis="monitoring_citations.source_category = brand_owned（仅 manual_confirmed）",
            extra={"brand_domains": coverage["brand_domains"], "total_domains": coverage["total_domains"]},
        ),
        _dimension(
            "competitor_rank", "竞品位次", competitor["outrank"], competitor["compared"],
            definition="品牌位次不劣于最优竞品位次的样本占比；只统计双方都有位次的样本",
            basis="brand_list_rank vs monitoring_competitor_mentions.position(min)",
            extra={
                "brand_avg": competitor["brand_avg"],
                "competitor_avg": competitor["competitor_avg"],
                "compared_samples": competitor["compared"],
            },
        ),
        _dimension(
            "context_quality", "引用上下文质量", context["hit"], context["total"],
            definition="已复核引用的标题或摘要出现品牌名/别名的比例",
            basis="monitoring_citations.title / snippet × 品牌词表",
            extra={"terms": context["terms"], "page_types": context.get("page_types", [])},
        ),
    ]

    caveats = [
        "分项之间不可相加，本报告不提供综合评分。",
        "分母 < 10 的分项只呈现数字，不作为结论依据。",
        "失败、待复核与未完成样本已排除在分母之外，明细见 excluded。",
    ]
    if valid_answers == 0:
        caveats.append("当前筛选范围内没有有效样本，五个分项均无数值。")

    return {
        "generated_at": datetime.now(timezone.utc),
        "scope": {
            "round_id": str(round_id) if round_id else None,
            "engine_id": str(engine_id) if engine_id else None,
            "question_id": str(question_id) if question_id else None,
            "start_at": start_at,
            "end_at": end_at,
            "answer_kind": answer_kind.value if answer_kind else None,
            "question_type": str(question_type) if question_type else None,
            "valid_answers": valid_answers,
            "excluded": excluded,
        },
        "dimensions": dimensions,
        "caveats": caveats,
    }
