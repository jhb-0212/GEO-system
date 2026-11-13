"""看板指标口径（第 4 节）：统一在这里算，B 的看板接口直接调用，不要各写一套 SQL。

口径（必须与 `docs/指标口径.md` / `MetricDefinition` 保持一致）：

- 有效回答（分母）：`monitoring_samples.status IN ('hit', 'miss')`。
  `failed` / `manual_review` / `pending` / `running` 一律不进分母。
- 品牌提及率分子：有效回答中 `monitoring_samples.brand_mentioned IS TRUE`。
- 引用率分子：有效回答中，至少存在一条
  `monitoring_citations.is_brand_related IS TRUE`
  且 `monitoring_citations.review_status = 'manual_confirmed'` 的引用。
  注意：系统枚举没有 `confirmed`，人工复核通过的实际值是 `manual_confirmed`；
  `auto`（自动判定未复核）不能等同于“已复核”。
- 渠道数：有效回答关联引用中按 `monitoring_citations.channel_id` 去重。
- 页面数：有效回答关联引用中按 `monitoring_citations.normalized_url` 去重；
  `normalized_url` 为空的不计入页面数。

所有函数只读数据库，不提交事务；无有效回答时分母为 0，比率返回 `None` 而不是 0，
避免看板把“没有数据”误显示成“0%”。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, exists, func, select
from sqlalchemy.orm import Session

from app.models import (
    AiEngine,
    AiEngineEntry,
    Channel,
    Competitor,
    Lead,
    MonitoringCitation,
    MonitoringCompetitorMention,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    CitationReviewStatus,
    CitationUsage,
    QuestionStatus,
    SampleStatus,
)

VALID_SAMPLE_STATUSES = (SampleStatus.HIT, SampleStatus.MISS)
CONFIRMED_REVIEW_STATUS = CitationReviewStatus.MANUAL_CONFIRMED


def _status_value(status: object) -> str:
    value = getattr(status, "value", status)
    return str(value)


def _sample_scope(
    project_id: uuid.UUID,
    *,
    round_id: uuid.UUID | None = None,
    engine_id: uuid.UUID | None = None,
    question_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
):
    """返回带项目/轮次/引擎/问题/时间过滤的 Sample 查询，不预设状态。"""
    stmt = (
        select(MonitoringSample)
        .join(MonitoringTask, MonitoringSample.task_id == MonitoringTask.id)
        .join(QuestionVersion, MonitoringTask.question_version_id == QuestionVersion.id)
        .join(AiEngineEntry, MonitoringTask.engine_entry_id == AiEngineEntry.id)
        .where(
            MonitoringSample.project_id == project_id,
            MonitoringTask.project_id == project_id,
            QuestionVersion.project_id == project_id,
        )
    )
    if round_id is not None:
        stmt = stmt.where(MonitoringTask.round_id == round_id)
    if engine_id is not None:
        stmt = stmt.where(AiEngineEntry.engine_id == engine_id)
    if question_id is not None:
        stmt = stmt.where(QuestionVersion.question_id == question_id)
    if start_at is not None:
        stmt = stmt.where(MonitoringSample.sampled_at >= start_at)
    if end_at is not None:
        stmt = stmt.where(MonitoringSample.sampled_at <= end_at)
    return stmt


def _valid_sample_scope(
    project_id: uuid.UUID,
    *,
    round_id: uuid.UUID | None = None,
    engine_id: uuid.UUID | None = None,
    question_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
):
    return _sample_scope(
        project_id,
        round_id=round_id,
        engine_id=engine_id,
        question_id=question_id,
        start_at=start_at,
        end_at=end_at,
    ).where(MonitoringSample.status.in_(VALID_SAMPLE_STATUSES))


def _citation_scope(
    project_id: uuid.UUID,
    *,
    round_id: uuid.UUID | None = None,
    engine_id: uuid.UUID | None = None,
    question_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
):
    """引用查询，仅覆盖有效回答；用于渠道/页面去重。"""
    stmt = (
        select(MonitoringCitation)
        .join(MonitoringSample, MonitoringCitation.sample_id == MonitoringSample.id)
        .join(MonitoringTask, MonitoringSample.task_id == MonitoringTask.id)
        .join(QuestionVersion, MonitoringTask.question_version_id == QuestionVersion.id)
        .join(AiEngineEntry, MonitoringTask.engine_entry_id == AiEngineEntry.id)
        .where(
            MonitoringCitation.project_id == project_id,
            MonitoringSample.project_id == project_id,
            MonitoringTask.project_id == project_id,
            MonitoringSample.status.in_(VALID_SAMPLE_STATUSES),
        )
    )
    if round_id is not None:
        stmt = stmt.where(MonitoringTask.round_id == round_id)
    if engine_id is not None:
        stmt = stmt.where(AiEngineEntry.engine_id == engine_id)
    if question_id is not None:
        stmt = stmt.where(QuestionVersion.question_id == question_id)
    if start_at is not None:
        stmt = stmt.where(MonitoringSample.sampled_at >= start_at)
    if end_at is not None:
        stmt = stmt.where(MonitoringSample.sampled_at <= end_at)
    return stmt


def _count(stmt, db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _brand_citation_exists(project_id: uuid.UUID):
    """相关子查询：当前 sample 是否有至少一条“基地相关且人工复核通过”的引用。"""
    return exists(
        select(1)
        .select_from(MonitoringCitation)
        .where(
            MonitoringCitation.sample_id == MonitoringSample.id,
            MonitoringCitation.project_id == project_id,
            MonitoringCitation.is_brand_related.is_(True),
            MonitoringCitation.review_status == CONFIRMED_REVIEW_STATUS,
        )
    )


def overview(
    db: Session,
    project_id: uuid.UUID,
    *,
    round_id: uuid.UUID | None = None,
    engine_id: uuid.UUID | None = None,
    question_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> dict:
    """项目总览：分母严格 hit/miss，失败与待复核单独计数，不混入分母。"""
    valid_scope = _valid_sample_scope(
        project_id,
        round_id=round_id,
        engine_id=engine_id,
        question_id=question_id,
        start_at=start_at,
        end_at=end_at,
    )
    valid_answers = _count(valid_scope, db)
    brand_mentioned_answers = _count(
        valid_scope.where(MonitoringSample.brand_mentioned.is_(True)), db
    )
    citation_answers = _count(
        valid_scope.where(_brand_citation_exists(project_id)), db
    )

    citation_scope = _citation_scope(
        project_id,
        round_id=round_id,
        engine_id=engine_id,
        question_id=question_id,
        start_at=start_at,
        end_at=end_at,
    )
    citation_subquery = citation_scope.subquery()
    channel_count = int(
        db.scalar(
            select(func.count(func.distinct(citation_subquery.c.channel_id)))
            .select_from(citation_subquery)
        )
        or 0
    )
    page_count = int(
        db.scalar(
            select(func.count(func.distinct(citation_subquery.c.normalized_url)))
            .select_from(citation_subquery)
        )
        or 0
    )

    all_scope = _sample_scope(
        project_id,
        round_id=round_id,
        engine_id=engine_id,
        question_id=question_id,
        start_at=start_at,
        end_at=end_at,
    )
    all_subquery = all_scope.subquery()
    status_counts_rows = db.execute(
        select(all_subquery.c.status, func.count())
        .select_from(all_subquery)
        .group_by(all_subquery.c.status)
    ).all()
    status_counts = {_status_value(status): int(count) for status, count in status_counts_rows}

    excluded = {
        "failed": status_counts.get(SampleStatus.FAILED.value, 0),
        "manual_review": status_counts.get(SampleStatus.MANUAL_REVIEW.value, 0),
        "pending_or_running": (
            status_counts.get(SampleStatus.PENDING.value, 0)
            + status_counts.get(SampleStatus.RUNNING.value, 0)
        ),
    }
    return {
        "valid_answers": valid_answers,
        "brand_mentioned_answers": brand_mentioned_answers,
        "citation_answers": citation_answers,
        "brand_mention_rate": _rate(brand_mentioned_answers, valid_answers),
        "citation_rate": _rate(citation_answers, valid_answers),
        "channel_count": channel_count,
        "page_count": page_count,
        "excluded": excluded,
    }


def _grouped_metrics(
    db: Session,
    project_id: uuid.UUID,
    group_columns,
    *,
    round_id: uuid.UUID | None = None,
    engine_id: uuid.UUID | None = None,
    question_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
):
    citation_exists = _brand_citation_exists(project_id)
    stmt = (
        select(
            *group_columns,
            func.count(MonitoringSample.id).label("valid_answers"),
            func.sum(
                case((MonitoringSample.brand_mentioned.is_(True), 1), else_=0)
            ).label("brand_mentioned_answers"),
            func.sum(case((citation_exists, 1), else_=0)).label("citation_answers"),
        )
        .select_from(MonitoringSample)
        .join(MonitoringTask, MonitoringSample.task_id == MonitoringTask.id)
        .join(QuestionVersion, MonitoringTask.question_version_id == QuestionVersion.id)
        .join(AiEngineEntry, MonitoringTask.engine_entry_id == AiEngineEntry.id)
        .where(
            MonitoringSample.project_id == project_id,
            MonitoringTask.project_id == project_id,
            QuestionVersion.project_id == project_id,
            MonitoringSample.status.in_(VALID_SAMPLE_STATUSES),
        )
        .group_by(*group_columns)
    )
    if round_id is not None:
        stmt = stmt.where(MonitoringTask.round_id == round_id)
    if engine_id is not None:
        stmt = stmt.where(AiEngineEntry.engine_id == engine_id)
    if question_id is not None:
        stmt = stmt.where(QuestionVersion.question_id == question_id)
    if start_at is not None:
        stmt = stmt.where(MonitoringSample.sampled_at >= start_at)
    if end_at is not None:
        stmt = stmt.where(MonitoringSample.sampled_at <= end_at)
    return stmt


def by_engine(
    db: Session,
    project_id: uuid.UUID,
    *,
    round_id: uuid.UUID | None = None,
    engine_id: uuid.UUID | None = None,
    question_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> list[dict]:
    """分引擎对比：每个引擎单独算同一套 hit/miss 分母口径。"""
    stmt = _grouped_metrics(
        db,
        project_id,
        (AiEngine.id, AiEngine.code, AiEngine.name),
        round_id=round_id,
        engine_id=engine_id,
        question_id=question_id,
        start_at=start_at,
        end_at=end_at,
    ).join(AiEngine, AiEngineEntry.engine_id == AiEngine.id).order_by(AiEngine.code)

    rows = db.execute(stmt).all()
    result = []
    for engine_pk, engine_code, engine_name, valid_answers, brand_count, citation_count in rows:
        valid_answers = int(valid_answers or 0)
        brand_count = int(brand_count or 0)
        citation_count = int(citation_count or 0)
        result.append(
            {
                "engine_id": str(engine_pk),
                "engine_code": engine_code,
                "engine_name": engine_name,
                "valid_answers": valid_answers,
                "brand_mentioned_answers": brand_count,
                "citation_answers": citation_count,
                "brand_mention_rate": _rate(brand_count, valid_answers),
                "citation_rate": _rate(citation_count, valid_answers),
            }
        )
    return result


def by_question(
    db: Session,
    project_id: uuid.UUID,
    *,
    round_id: uuid.UUID | None = None,
    engine_id: uuid.UUID | None = None,
    question_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> list[dict]:
    """分问题对比：返回 question_type，调用方可按品牌题/通用题分开展示。"""
    stmt = _grouped_metrics(
        db,
        project_id,
        (Question.id, Question.code, Question.title, Question.question_type),
        round_id=round_id,
        engine_id=engine_id,
        question_id=question_id,
        start_at=start_at,
        end_at=end_at,
    ).join(Question, QuestionVersion.question_id == Question.id).order_by(Question.code)

    rows = db.execute(stmt).all()
    result = []
    for question_pk, code, title, question_type, valid_answers, brand_count, citation_count in rows:
        valid_answers = int(valid_answers or 0)
        brand_count = int(brand_count or 0)
        citation_count = int(citation_count or 0)
        result.append(
            {
                "question_id": str(question_pk),
                "question_code": code,
                "question_title": title,
                "question_type": _status_value(question_type),
                "valid_answers": valid_answers,
                "brand_mentioned_answers": brand_count,
                "citation_answers": citation_count,
                "brand_mention_rate": _rate(brand_count, valid_answers),
                "citation_rate": _rate(citation_count, valid_answers),
            }
        )
    return result


STATS_EXPORT_COLUMNS = (
    "record_type",
    "code",
    "name",
    "question_type",
    "valid_answers",
    "brand_mentioned_answers",
    "citation_answers",
    "brand_mention_rate",
    "citation_rate",
    "channel_count",
    "page_count",
    "failed_answers",
    "manual_review_answers",
    "pending_or_running_answers",
)


def export(
    db: Session,
    project_id: uuid.UUID,
    *,
    round_id: uuid.UUID | None = None,
    engine_id: uuid.UUID | None = None,
    question_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> list[dict]:
    """把总览、分引擎、分问题三张表摊平成一张 CSV 行集。

    三个视图都复用同一套 overview/by_engine/by_question 口径，导出层不再写 SQL，
    避免导出数字和看板数字对不上。
    """
    filters = {
        "round_id": round_id,
        "engine_id": engine_id,
        "question_id": question_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    overview_row = overview(db, project_id, **filters)
    excluded = overview_row["excluded"]
    rows: list[dict] = [
        {
            "record_type": "overview",
            "code": "OVERVIEW",
            "name": "项目总览",
            "question_type": "",
            "valid_answers": overview_row["valid_answers"],
            "brand_mentioned_answers": overview_row["brand_mentioned_answers"],
            "citation_answers": overview_row["citation_answers"],
            "brand_mention_rate": overview_row["brand_mention_rate"],
            "citation_rate": overview_row["citation_rate"],
            "channel_count": overview_row["channel_count"],
            "page_count": overview_row["page_count"],
            "failed_answers": excluded["failed"],
            "manual_review_answers": excluded["manual_review"],
            "pending_or_running_answers": excluded["pending_or_running"],
        }
    ]
    for item in by_engine(db, project_id, **filters):
        rows.append(
            {
                "record_type": "engine",
                "code": item["engine_code"],
                "name": item["engine_name"],
                "question_type": "",
                "valid_answers": item["valid_answers"],
                "brand_mentioned_answers": item["brand_mentioned_answers"],
                "citation_answers": item["citation_answers"],
                "brand_mention_rate": item["brand_mention_rate"],
                "citation_rate": item["citation_rate"],
                "channel_count": "",
                "page_count": "",
                "failed_answers": "",
                "manual_review_answers": "",
                "pending_or_running_answers": "",
            }
        )
    for item in by_question(db, project_id, **filters):
        rows.append(
            {
                "record_type": "question",
                "code": item["question_code"],
                "name": item["question_title"],
                "question_type": item["question_type"],
                "valid_answers": item["valid_answers"],
                "brand_mentioned_answers": item["brand_mentioned_answers"],
                "citation_answers": item["citation_answers"],
                "brand_mention_rate": item["brand_mention_rate"],
                "citation_rate": item["citation_rate"],
                "channel_count": "",
                "page_count": "",
                "failed_answers": "",
                "manual_review_answers": "",
                "pending_or_running_answers": "",
            }
        )
    return rows


def _lead_scope(
    project_id: uuid.UUID,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
):
    stmt = select(Lead).where(Lead.project_id == project_id)
    if start_at is not None:
        stmt = stmt.where(Lead.created_at >= start_at)
    if end_at is not None:
        stmt = stmt.where(Lead.created_at <= end_at)
    return stmt


def lead_funnel(
    db: Session,
    project_id: uuid.UUID,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> dict:
    """线索漏斗：总量、有效量、题目/渠道/引擎归因量与分组。

    分母为 0 时比率返回 None，避免看板把“没有线索”显示成 0%。
    """
    scope = _lead_scope(project_id, start_at=start_at, end_at=end_at)
    total = _count(scope, db)
    valid = _count(scope.where(Lead.is_valid.is_(True)), db)
    attributed_question = _count(scope.where(Lead.source_question_id.is_not(None)), db)
    attributed_channel = _count(scope.where(Lead.source_channel_id.is_not(None)), db)
    attributed_engine = _count(scope.where(Lead.source_engine_id.is_not(None)), db)

    by_question_rows = db.execute(
        select(Question.code, Question.title, func.count(Lead.id))
        .join(Lead, Lead.source_question_id == Question.id)
        .where(
            Lead.project_id == project_id,
            Lead.source_question_id.is_not(None),
            *([Lead.created_at >= start_at] if start_at is not None else []),
            *([Lead.created_at <= end_at] if end_at is not None else []),
        )
        .group_by(Question.code, Question.title)
        .order_by(func.count(Lead.id).desc(), Question.code)
    ).all()
    by_channel_rows = db.execute(
        select(Channel.code, Channel.name, func.count(Lead.id))
        .join(Lead, Lead.source_channel_id == Channel.id)
        .where(
            Lead.project_id == project_id,
            Lead.source_channel_id.is_not(None),
            *([Lead.created_at >= start_at] if start_at is not None else []),
            *([Lead.created_at <= end_at] if end_at is not None else []),
        )
        .group_by(Channel.code, Channel.name)
        .order_by(func.count(Lead.id).desc(), Channel.code)
    ).all()
    by_engine_rows = db.execute(
        select(AiEngine.code, AiEngine.name, func.count(Lead.id))
        .join(Lead, Lead.source_engine_id == AiEngine.id)
        .where(
            Lead.project_id == project_id,
            Lead.source_engine_id.is_not(None),
            *([Lead.created_at >= start_at] if start_at is not None else []),
            *([Lead.created_at <= end_at] if end_at is not None else []),
        )
        .group_by(AiEngine.code, AiEngine.name)
        .order_by(func.count(Lead.id).desc(), AiEngine.code)
    ).all()

    return {
        "total_leads": total,
        "valid_leads": valid,
        "attributed_question": attributed_question,
        "attributed_channel": attributed_channel,
        "attributed_engine": attributed_engine,
        "question_attribution_rate": _rate(attributed_question, total),
        "channel_attribution_rate": _rate(attributed_channel, total),
        "engine_attribution_rate": _rate(attributed_engine, total),
        "by_question": [
            {"question_code": code, "question_title": title, "leads": int(count)}
            for code, title, count in by_question_rows
        ],
        "by_channel": [
            {"channel_code": code, "channel_name": name, "leads": int(count)}
            for code, name, count in by_channel_rows
        ],
        "by_engine": [
            {"engine_code": code, "engine_name": name, "leads": int(count)}
            for code, name, count in by_engine_rows
        ],
    }


def geo_overview(
    db: Session,
    project_id: uuid.UUID,
    *,
    round_id: uuid.UUID | None = None,
    engine_id: uuid.UUID | None = None,
    question_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    now: datetime | None = None,
) -> dict:
    """内部 GEO 验收指标：有效回答、提及率、引用份额、SOV、题库覆盖、新鲜度、失败率。

    口径固定写进返回的 `definitions`，避免报告端自行解释：
    - mention_rate = 品牌提及的有效回答 / 有效回答；
    - citation_share = 品牌相关引用 / 全部引用（只统计有效回答关联的引用）；
    - sov = 有品牌提及的有效回答 /（有品牌提及的有效回答 + 有竞品提及的有效回答）；
    - prompt_coverage = 有有效回答的 active 题目 / active 题目；
    - failure_rate = failed 样本 / 全部样本（含 pending/running，明确不是有效分母）；
    - freshness = 最近一条有效回答距 now 的小时数，以及 24 小时内有效回答占比；
    - valid_answers = status in (hit, miss) 的样本数。
    """
    moment = now or datetime.now(timezone.utc)
    valid_scope = _valid_sample_scope(
        project_id,
        round_id=round_id,
        engine_id=engine_id,
        question_id=question_id,
        start_at=start_at,
        end_at=end_at,
    )
    all_scope = _sample_scope(
        project_id,
        round_id=round_id,
        engine_id=engine_id,
        question_id=question_id,
        start_at=start_at,
        end_at=end_at,
    )

    valid_answers = _count(valid_scope, db)
    total_samples = _count(all_scope, db)
    brand_mentioned_answers = _count(
        valid_scope.where(MonitoringSample.brand_mentioned.is_(True)), db
    )
    failed_samples = _count(all_scope.where(MonitoringSample.status == SampleStatus.FAILED), db)

    citation_scope = _citation_scope(
        project_id,
        round_id=round_id,
        engine_id=engine_id,
        question_id=question_id,
        start_at=start_at,
        end_at=end_at,
    )
    citation_total = _count(citation_scope, db)
    brand_citations = _count(
        citation_scope.where(MonitoringCitation.is_brand_related.is_(True)), db
    )
    confirmed_brand_citations = _count(
        citation_scope.where(
            MonitoringCitation.is_brand_related.is_(True),
            MonitoringCitation.review_status == CONFIRMED_REVIEW_STATUS,
        ),
        db,
    )
    used_citations = _count(
        citation_scope.where(MonitoringCitation.citation_usage == CitationUsage.USED), db
    )
    cited_citations = _count(
        citation_scope.where(MonitoringCitation.citation_usage == CitationUsage.CITED), db
    )

    valid_ids = select(valid_scope.subquery().c.id)
    competitor_mentioned_samples = int(
        db.scalar(
            select(func.count(func.distinct(MonitoringCompetitorMention.sample_id)))
            .select_from(MonitoringCompetitorMention)
            .where(
                MonitoringCompetitorMention.project_id == project_id,
                MonitoringCompetitorMention.sample_id.in_(valid_ids),
            )
        )
        or 0
    )
    competitor_rows = db.execute(
        select(
            Competitor.name,
            func.count(func.distinct(MonitoringCompetitorMention.sample_id)),
        )
        .select_from(MonitoringCompetitorMention)
        .join(Competitor, Competitor.id == MonitoringCompetitorMention.competitor_id)
        .where(
            MonitoringCompetitorMention.project_id == project_id,
            MonitoringCompetitorMention.sample_id.in_(valid_ids),
        )
        .group_by(Competitor.name)
        .order_by(func.count(func.distinct(MonitoringCompetitorMention.sample_id)).desc(), Competitor.name)
    ).all()
    sov_denominator = brand_mentioned_answers + competitor_mentioned_samples
    sov = _rate(brand_mentioned_answers, sov_denominator)

    active_question_count = int(
        db.scalar(
            select(func.count())
            .select_from(Question)
            .where(Question.project_id == project_id, Question.status == QuestionStatus.ACTIVE)
        )
        or 0
    )
    covered_questions = int(
        db.scalar(
            select(func.count(func.distinct(QuestionVersion.question_id)))
            .select_from(MonitoringSample)
            .join(MonitoringTask, MonitoringSample.task_id == MonitoringTask.id)
            .join(QuestionVersion, MonitoringTask.question_version_id == QuestionVersion.id)
            .join(AiEngineEntry, MonitoringTask.engine_entry_id == AiEngineEntry.id)
            .where(
                MonitoringSample.project_id == project_id,
                MonitoringSample.status.in_(VALID_SAMPLE_STATUSES),
                MonitoringTask.project_id == project_id,
                QuestionVersion.project_id == project_id,
                *([MonitoringTask.round_id == round_id] if round_id is not None else []),
                *([AiEngineEntry.engine_id == engine_id] if engine_id is not None else []),
                *([QuestionVersion.question_id == question_id] if question_id is not None else []),
                *([MonitoringSample.sampled_at >= start_at] if start_at is not None else []),
                *([MonitoringSample.sampled_at <= end_at] if end_at is not None else []),
            )
        )
        or 0
    )

    latest_sample_at = db.scalar(
        select(func.max(valid_scope.subquery().c.sampled_at))
    )
    latest_age_hours = None
    if latest_sample_at is not None:
        latest_age_hours = round(
            max(0.0, (moment - latest_sample_at).total_seconds() / 3600), 2
        )
    fresh_samples = _count(
        valid_scope.where(MonitoringSample.sampled_at >= moment - timedelta(hours=24)),
        db,
    )

    statement = (
        f"有效回答 {valid_answers}；当前仅为技术链路基线，不构成 GEO 内容结论"
        if valid_answers == 0
        else f"有效回答 {valid_answers}；以下比率均以有效回答或有效引用为分母"
    )

    return {
        "valid_answers": valid_answers,
        "mention_rate": _rate(brand_mentioned_answers, valid_answers),
        "citation_share": _rate(brand_citations, citation_total),
        "sov": sov,
        "prompt_coverage": _rate(covered_questions, active_question_count),
        "freshness_hours": latest_age_hours,
        "fresh_24h_rate": _rate(fresh_samples, valid_answers),
        "failure_rate": _rate(failed_samples, total_samples),
        "statement": statement,
        "counts": {
            "total_samples": total_samples,
            "valid_answers": valid_answers,
            "brand_mentioned_answers": brand_mentioned_answers,
            "failed_samples": failed_samples,
            "competitor_mentioned_samples": competitor_mentioned_samples,
            "citation_total": citation_total,
            "brand_citations": brand_citations,
            "confirmed_brand_citations": confirmed_brand_citations,
            "used_citations": used_citations,
            "cited_citations": cited_citations,
            "active_questions": active_question_count,
            "covered_questions": covered_questions,
        },
        "by_competitor": [
            {"competitor": name, "mentioned_samples": int(count)}
            for name, count in competitor_rows
        ],
        "definitions": {
            "valid_answers": "monitoring_samples.status in (hit, miss)",
            "mention_rate": "brand_mentioned_answers / valid_answers",
            "citation_share": "brand_citations / citation_total",
            "sov": "brand_mentioned_answers / (brand_mentioned_answers + competitor_mentioned_samples)",
            "prompt_coverage": "covered_questions / active_questions",
            "failure_rate": "failed_samples / total_samples",
            "freshness_hours": "now - latest valid sample sampled_at",
        },
    }