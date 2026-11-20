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

import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.engine_credentials import resolve_entry_secret

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
    Project,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    AnswerKind,
    CitationReviewStatus,
    CitationUsage,
    QuestionStatus,
    QuestionType,
    SampleStatus,
)
from app.services.brand_profile import build_vocabulary

VALID_SAMPLE_STATUSES = (SampleStatus.HIT, SampleStatus.MISS)
CONFIRMED_REVIEW_STATUS = CitationReviewStatus.MANUAL_CONFIRMED


def _status_value(status: object) -> str:
    value = getattr(status, "value", status)
    return str(value)


def _answer_kind_scope(stmt, answer_kind: AnswerKind | None):
    """答案口径过滤：NULL 视为未声明，按 answer 兜底（与模型注释一致）。"""
    if answer_kind is None:
        return stmt
    if answer_kind == AnswerKind.ANSWER:
        return stmt.where(
            or_(
                MonitoringSample.answer_kind == AnswerKind.ANSWER.value,
                MonitoringSample.answer_kind.is_(None),
            )
        )
    return stmt.where(MonitoringSample.answer_kind == answer_kind.value)


def _question_type_expr():
    """题目分区表达式：优先用版本快照，旧版本没快照时回退当前题目。

    品牌题是产品功能验证，通用题才是自然发现口径；两者混算会把品牌题的
    “被点名”稀释进自然发现率，因此统计层必须能按 question_type 隔离。
    """
    return func.coalesce(
        QuestionVersion.question_type,
        select(Question.question_type)
        .where(Question.id == QuestionVersion.question_id)
        .correlate(QuestionVersion)
        .scalar_subquery(),
    )


def _question_type_value(question_type: QuestionType | str | None) -> str | None:
    value = question_type.value if isinstance(question_type, QuestionType) else question_type
    if value in (None, "", "all"):
        return None
    return value


def _question_type_scope(stmt, question_type: QuestionType | str | None):
    value = _question_type_value(question_type)
    if value is None:
        return stmt
    return stmt.where(_question_type_expr() == value)


def _sample_scope(
    project_id: uuid.UUID,
    *,
    round_id: uuid.UUID | None = None,
    engine_id: uuid.UUID | None = None,
    question_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    answer_kind: AnswerKind | None = None,
    question_type: QuestionType | str | None = None,
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
    stmt = _answer_kind_scope(stmt, answer_kind)
    return _question_type_scope(stmt, question_type)


def _valid_sample_scope(
    project_id: uuid.UUID,
    *,
    round_id: uuid.UUID | None = None,
    engine_id: uuid.UUID | None = None,
    question_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    answer_kind: AnswerKind | None = None,
    question_type: QuestionType | str | None = None,
):
    return _sample_scope(
        project_id,
        round_id=round_id,
        engine_id=engine_id,
        question_id=question_id,
        start_at=start_at,
        end_at=end_at,
        answer_kind=answer_kind,
        question_type=question_type,
    ).where(MonitoringSample.status.in_(VALID_SAMPLE_STATUSES))


def _citation_scope(
    project_id: uuid.UUID,
    *,
    round_id: uuid.UUID | None = None,
    engine_id: uuid.UUID | None = None,
    question_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    answer_kind: AnswerKind | None = None,
    question_type: QuestionType | str | None = None,
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
    stmt = _answer_kind_scope(stmt, answer_kind)
    return _question_type_scope(stmt, question_type)


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
    answer_kind: AnswerKind | None = None,
    question_type: QuestionType | str | None = None,
) -> dict:
    """项目总览：分母严格 hit/miss，失败与待复核单独计数，不混入分母。

    两个容易被误读的计数（`page_count` / `channel_count`）都是**引用口径**，与登记表无关：
    - `page_count` = 引用里 `normalized_url` 去掉重复后的页面数，不等于 `public_pages` 登记的公司站页面数；
    - `channel_count` = 引用上 `channel_id` 的去重数，引用没回填渠道时就是 0。
    """
    valid_scope = _valid_sample_scope(
        project_id,
        round_id=round_id,
        engine_id=engine_id,
        question_id=question_id,
        start_at=start_at,
        end_at=end_at,
        answer_kind=answer_kind,
        question_type=question_type,
    )
    valid_answers = _count(valid_scope, db)
    brand_mentioned_answers = _count(
        valid_scope.where(MonitoringSample.brand_mentioned.is_(True)), db
    )
    brand_identified_answers = _count(
        valid_scope.where(MonitoringSample.brand_identified.is_(True)), db
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
        answer_kind=answer_kind,
        question_type=question_type,
    )
    # 计划口径：渠道数与去重页面数都只统计“已人工复核”的引用。
    reviewed_citation_subquery = citation_scope.where(
        MonitoringCitation.review_status == CONFIRMED_REVIEW_STATUS
    ).subquery()
    channel_count = int(
        db.scalar(
            select(func.count(func.distinct(reviewed_citation_subquery.c.channel_id)))
            .select_from(reviewed_citation_subquery)
            .where(reviewed_citation_subquery.c.channel_id.is_not(None))
        )
        or 0
    )
    page_count = int(
        db.scalar(
            select(func.count(func.distinct(reviewed_citation_subquery.c.normalized_url)))
            .select_from(reviewed_citation_subquery)
            .where(reviewed_citation_subquery.c.normalized_url.is_not(None))
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
        answer_kind=answer_kind,
        question_type=question_type,
    )
    all_subquery = all_scope.subquery()
    status_counts_rows = db.execute(
        select(all_subquery.c.status, func.count())
        .select_from(all_subquery)
        .group_by(all_subquery.c.status)
    ).all()
    status_counts = {_status_value(status): int(count) for status, count in status_counts_rows}
    failure_rows = db.execute(
        select(all_subquery.c.failure_code, func.count())
        .select_from(all_subquery)
        .where(all_subquery.c.status == SampleStatus.FAILED.value)
        .group_by(all_subquery.c.failure_code)
    ).all()
    failure_breakdown = {
        _status_value(code) if code is not None else "unknown": int(count)
        for code, count in failure_rows
    }

    excluded = {
        "failed": status_counts.get(SampleStatus.FAILED.value, 0),
        "manual_review": status_counts.get(SampleStatus.MANUAL_REVIEW.value, 0),
        "no_answer_surface": status_counts.get(SampleStatus.NO_ANSWER_SURFACE.value, 0),
        "pending_or_running": (
            status_counts.get(SampleStatus.PENDING.value, 0)
            + status_counts.get(SampleStatus.RUNNING.value, 0)
        ),
    }
    return {
        "valid_answers": valid_answers,
        "brand_mentioned_answers": brand_mentioned_answers,
        "brand_identified_answers": brand_identified_answers,
        "citation_answers": citation_answers,
        "brand_mention_rate": _rate(brand_mentioned_answers, valid_answers),
        "brand_identified_rate": _rate(brand_identified_answers, valid_answers),
        "citation_rate": _rate(citation_answers, valid_answers),
        "channel_count": channel_count,
        "page_count": page_count,
        "excluded": excluded,
        "failure_breakdown": failure_breakdown,
    }


def overview_by_answer_kind(
    db: Session,
    project_id: uuid.UUID,
    *,
    round_id: uuid.UUID | None = None,
    engine_id: uuid.UUID | None = None,
    question_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    question_type: QuestionType | str | None = None,
) -> list[dict]:
    """按答案口径分组：answer / search_result 各自独立分母，禁止合并算提及率。"""
    return [
        {
            "answer_kind": kind.value,
            **overview(
                db,
                project_id,
                round_id=round_id,
                engine_id=engine_id,
                question_id=question_id,
                start_at=start_at,
                end_at=end_at,
                answer_kind=kind,
                question_type=question_type,
            ),
        }
        for kind in (AnswerKind.ANSWER, AnswerKind.SEARCH_RESULT)
    ]


def weekly_trend(
    db: Session,
    project_id: uuid.UUID,
    *,
    weeks: int = 12,
    now: datetime | None = None,
    answer_kind: AnswerKind | None = None,
) -> list[dict]:
    """周趋势：一次按周分桶聚合，不能对每周重复跑 overview 的十余条查询。

    口径与 `overview` 一致：分母仍是 hit/miss 有效回答，分子是 brand_mentioned；
    无有效回答的周 `brand_mention_rate` 返回 None，不显示成 0%。
    """
    current = now or datetime.now(timezone.utc)
    current_week = (current - timedelta(days=current.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    earliest = current_week - timedelta(weeks=max(0, weeks - 1))
    scope = _valid_sample_scope(
        project_id, start_at=earliest, answer_kind=answer_kind
    ).subquery()
    week_expr = func.date_trunc("week", scope.c.sampled_at)
    rows = db.execute(
        select(
            week_expr.label("week_start"),
            func.count().label("valid_answers"),
            func.count().filter(scope.c.brand_mentioned.is_(True)).label("mentioned"),
        )
        .group_by(week_expr)
        .order_by(week_expr)
    ).all()
    counts = {
        row.week_start.date(): (int(row.valid_answers), int(row.mentioned))
        for row in rows
    }

    result: list[dict] = []
    for offset in range(weeks - 1, -1, -1):
        week_start = current_week - timedelta(weeks=offset)
        valid_answers, mentioned = counts.get(week_start.date(), (0, 0))
        result.append({
            "week_start": week_start,
            "valid_answers": valid_answers,
            "brand_mention_rate": _rate(mentioned, valid_answers),
        })
    return result


def daily_trend(
    db: Session,
    project_id: uuid.UUID,
    *,
    days: int = 30,
    now: datetime | None = None,
    answer_kind: AnswerKind | None = None,
) -> list[dict]:
    """按天趋势：与周趋势同一口径，只把分桶粒度换成自然日。"""
    current = now or datetime.now(timezone.utc)
    current_day = current.replace(hour=0, minute=0, second=0, microsecond=0)
    earliest = current_day - timedelta(days=max(0, days - 1))
    scope = _valid_sample_scope(
        project_id, start_at=earliest, answer_kind=answer_kind
    ).subquery()
    day_expr = func.date_trunc("day", scope.c.sampled_at)
    rows = db.execute(
        select(
            day_expr.label("date"),
            func.count().label("valid_answers"),
            func.count().filter(scope.c.brand_mentioned.is_(True)).label("mentioned"),
        )
        .group_by(day_expr)
        .order_by(day_expr)
    ).all()
    counts = {
        row.date.date(): (int(row.valid_answers), int(row.mentioned))
        for row in rows
    }

    result: list[dict] = []
    for offset in range(days - 1, -1, -1):
        day = current_day - timedelta(days=offset)
        valid_answers, mentioned = counts.get(day.date(), (0, 0))
        result.append({
            "date": day,
            "week_start": day,
            "valid_answers": valid_answers,
            "brand_mention_rate": _rate(mentioned, valid_answers),
        })
    return result


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
    answer_kind: AnswerKind | None = None,
    question_type: QuestionType | str | None = None,
):
    citation_exists = _brand_citation_exists(project_id)
    stmt = (
        select(
            *group_columns,
            func.count(MonitoringSample.id).label("valid_answers"),
            func.sum(
                case((MonitoringSample.brand_mentioned.is_(True), 1), else_=0)
            ).label("brand_mentioned_answers"),
            func.sum(
                case((MonitoringSample.brand_identified.is_(True), 1), else_=0)
            ).label("brand_identified_answers"),
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
    stmt = _answer_kind_scope(stmt, answer_kind)
    return _question_type_scope(stmt, question_type)


def by_engine(
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
        answer_kind=answer_kind,
        question_type=question_type,
    ).join(AiEngine, AiEngineEntry.engine_id == AiEngine.id).order_by(AiEngine.code)

    rows = db.execute(stmt).all()
    result = []
    for engine_pk, engine_code, engine_name, valid_answers, brand_count, identified_count, citation_count in rows:
        valid_answers = int(valid_answers or 0)
        brand_count = int(brand_count or 0)
        identified_count = int(identified_count or 0)
        citation_count = int(citation_count or 0)
        result.append(
            {
                "engine_id": str(engine_pk),
                "engine_code": engine_code,
                "engine_name": engine_name,
                "valid_answers": valid_answers,
                "brand_mentioned_answers": brand_count,
                "brand_identified_answers": identified_count,
                "citation_answers": citation_count,
                "brand_mention_rate": _rate(brand_count, valid_answers),
                "brand_identified_rate": _rate(identified_count, valid_answers),
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
    answer_kind: AnswerKind | None = None,
    question_type: QuestionType | str | None = None,
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
        answer_kind=answer_kind,
        question_type=question_type,
    ).join(Question, QuestionVersion.question_id == Question.id).order_by(Question.code)

    rows = db.execute(stmt).all()
    result = []
    for question_pk, code, title, question_type, valid_answers, brand_count, identified_count, citation_count in rows:
        valid_answers = int(valid_answers or 0)
        brand_count = int(brand_count or 0)
        identified_count = int(identified_count or 0)
        citation_count = int(citation_count or 0)
        result.append(
            {
                "question_id": str(question_pk),
                "question_code": code,
                "question_title": title,
                "question_type": _status_value(question_type),
                "valid_answers": valid_answers,
                "brand_mentioned_answers": brand_count,
                "brand_identified_answers": identified_count,
                "citation_answers": citation_count,
                "brand_mention_rate": _rate(brand_count, valid_answers),
                "brand_identified_rate": _rate(identified_count, valid_answers),
                "citation_rate": _rate(citation_count, valid_answers),
            }
        )
    return result


STATS_EXPORT_COLUMNS = (
    "answer_kind",
    "record_type",
    "code",
    "name",
    "question_type",
    "valid_answers",
    "brand_mentioned_answers",
    "brand_identified_answers",
    "citation_answers",
    "brand_mention_rate",
    "brand_identified_rate",
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
    answer_kind: AnswerKind | None = None,
    question_type: QuestionType | str | None = None,
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
        "answer_kind": answer_kind,
        "question_type": question_type,
    }
    overview_row = overview(db, project_id, **filters)
    excluded = overview_row["excluded"]
    kind_label = answer_kind.value if answer_kind is not None else "all"
    rows: list[dict] = [
        {
            "answer_kind": kind_label,
            "record_type": "overview",
            "code": "OVERVIEW",
            "name": "项目总览",
            "question_type": "",
            "valid_answers": overview_row["valid_answers"],
            "brand_mentioned_answers": overview_row["brand_mentioned_answers"],
            "brand_identified_answers": overview_row["brand_identified_answers"],
            "citation_answers": overview_row["citation_answers"],
            "brand_mention_rate": overview_row["brand_mention_rate"],
            "brand_identified_rate": overview_row["brand_identified_rate"],
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
                "answer_kind": kind_label,
                "record_type": "engine",
                "code": item["engine_code"],
                "name": item["engine_name"],
                "question_type": "",
                "valid_answers": item["valid_answers"],
                "brand_mentioned_answers": item["brand_mentioned_answers"],
                "brand_identified_answers": item["brand_identified_answers"],
                "citation_answers": item["citation_answers"],
                "brand_mention_rate": item["brand_mention_rate"],
                "brand_identified_rate": item["brand_identified_rate"],
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
                "answer_kind": kind_label,
                "record_type": "question",
                "code": item["question_code"],
                "name": item["question_title"],
                "question_type": item["question_type"],
                "valid_answers": item["valid_answers"],
                "brand_mentioned_answers": item["brand_mentioned_answers"],
                "brand_identified_answers": item["brand_identified_answers"],
                "citation_answers": item["citation_answers"],
                "brand_mention_rate": item["brand_mention_rate"],
                "brand_identified_rate": item["brand_identified_rate"],
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


POSITIVE_TERMS = (
    "推荐", "适合", "优势", "领先", "可靠", "优质", "不错", "值得", "专业", "高效", "稳定", "满意",
)
NEGATIVE_TERMS = (
    "不推荐", "不适合", "劣势", "落后", "不可靠", "差", "风险", "投诉", "失败", "不专业", "贵", "差评",
)
_SENTENCE_SPLIT = re.compile(r"[。！？!?；;\n]+")


def _brand_sentiment(text: str | None, brand_terms: list[str]) -> tuple[str, int]:
    """规则词典情感：只看包含品牌的句子，不把竞品评价算到品牌头上。

    `brand_terms` 传入的是“品牌出现词表”——正式名 + 别名 + 唯一标识（地址/电话/公众号）。
    为什么把标识也算进来：只点名没给标识的答案与只给标识没点名的答案，**句子讲的都是品牌**，
    如果只认品牌名，Q01 这类“答了地址电话但没复述品牌名”的回答就被记成 not_mentioned，
    情感维度会整段瞎掉。标识词表未配置时这里等价于只认品牌名，历史口径不变。
    """
    if not text:
        return "not_mentioned", 0
    folded_terms = [term.casefold() for term in brand_terms if term]
    sentences = [
        sentence
        for sentence in _SENTENCE_SPLIT.split(text)
        if sentence.strip() and any(term in sentence.casefold() for term in folded_terms)
    ]
    if not sentences:
        return "not_mentioned", 0
    joined = " ".join(sentences).casefold()
    positive = sum(joined.count(term) for term in POSITIVE_TERMS)
    negative = sum(joined.count(term) for term in NEGATIVE_TERMS)
    score = positive - negative
    if score > 0:
        return "positive", score
    if score < 0:
        return "negative", score
    return "neutral", 0


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
    answer_kind: AnswerKind | None = None,
    question_type: QuestionType | str | None = None,
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
        answer_kind=answer_kind,
        question_type=question_type,
    )
    all_scope = _sample_scope(
        project_id,
        round_id=round_id,
        engine_id=engine_id,
        question_id=question_id,
        start_at=start_at,
        end_at=end_at,
        answer_kind=answer_kind,
        question_type=question_type,
    )

    valid_answers = _count(valid_scope, db)
    total_samples = _count(all_scope, db)
    brand_mentioned_answers = _count(
        valid_scope.where(MonitoringSample.brand_mentioned.is_(True)), db
    )
    # 可识别口径：答案没点名、但给出了品牌唯一标识（地址/电话/公众号）的有效回答。
    # 与 mention_rate 并行呈现，不参与 sov（sov 只比“点名提及”）。
    brand_identified_answers = _count(
        valid_scope.where(MonitoringSample.brand_identified.is_(True)), db
    )
    failed_samples = _count(all_scope.where(MonitoringSample.status == SampleStatus.FAILED), db)

    citation_scope = _citation_scope(
        project_id,
        round_id=round_id,
        engine_id=engine_id,
        question_id=question_id,
        start_at=start_at,
        end_at=end_at,
        answer_kind=answer_kind,
        question_type=question_type,
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
    competitor_mentions = int(
        db.scalar(
            select(func.count())
            .select_from(MonitoringCompetitorMention)
            .where(
                MonitoringCompetitorMention.project_id == project_id,
                MonitoringCompetitorMention.sample_id.in_(valid_ids),
            )
        )
        or 0
    )
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
    sov_denominator = brand_mentioned_answers + competitor_mentions
    sov = _rate(brand_mentioned_answers, sov_denominator)

    project = db.get(Project, project_id)
    # 品牌词表统一从品牌实体配置取；未配置时回退项目名/项目 code，历史口径不变。
    vocabulary = build_vocabulary(db, project_id, project=project)
    brand_terms = vocabulary.mention_terms
    # 情感/位次用的是“品牌出现词表”：点名词 + 唯一标识。
    # 只认点名会让“答了地址电话但没复述品牌名”的答案整段判 not_mentioned，情感维度失真。
    presence_terms = [*vocabulary.mention_terms, *vocabulary.identifier_terms]
    # 位次只认 A6 落库的列表位次：正文散文顺序不是搜索排名，不能再按首现序号伪造。
    valid_answer_rows = db.execute(
        valid_scope.with_only_columns(
            MonitoringSample.raw_answer,
            MonitoringSample.brand_list_rank,
            maintain_column_froms=True,
        ).execution_options(yield_per=1000)
    )
    sentiment_counts = {"positive": 0, "neutral": 0, "negative": 0, "not_mentioned": 0}
    sentiment_scores: list[int] = []
    brand_ranks: list[int] = []
    for raw_answer, list_rank in valid_answer_rows:
        label, score = _brand_sentiment(raw_answer, presence_terms)
        sentiment_counts[label] += 1
        if label != "not_mentioned":
            sentiment_scores.append(score)
        if list_rank is not None and 1 <= int(list_rank) <= 50:
            brand_ranks.append(int(list_rank))

    judged_sentiment = sum(
        sentiment_counts[label] for label in ("positive", "neutral", "negative")
    )
    sentiment_result = {
        **sentiment_counts,
        "positive_rate": _rate(sentiment_counts["positive"], judged_sentiment),
        "average_score": (
            round(sum(sentiment_scores) / len(sentiment_scores), 2)
            if sentiment_scores
            else None
        ),
        # 规则词典只是复核线索，不是 KPI；前端不得把它当 headline 指标。
        "kpi_eligible": False,
        "basis": "rule_lexicon_v1",
    }
    position_result = {
        "sample_count": len(brand_ranks),
        "average_rank": (
            round(sum(brand_ranks) / len(brand_ranks), 2) if brand_ranks else None
        ),
        "top1_rate": _rate(sum(1 for rank in brand_ranks if rank == 1), len(brand_ranks)),
    }

    question_type_value = _question_type_value(question_type)
    active_question_count = int(
        db.scalar(
            select(func.count())
            .select_from(Question)
            .where(
                Question.project_id == project_id,
                Question.status == QuestionStatus.ACTIVE,
                *(
                    [Question.question_type == question_type_value]
                    if question_type_value is not None
                    else []
                ),
            )
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
                *(
                    [_question_type_expr() == question_type_value]
                    if question_type_value is not None
                    else []
                ),
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
        "identified_rate": _rate(brand_identified_answers, valid_answers),
        "citation_share": _rate(brand_citations, citation_total),
        "sov": sov,
        "sentiment": sentiment_result,
        "brand_position": position_result,
        "prompt_coverage": _rate(covered_questions, active_question_count),
        "freshness_hours": latest_age_hours,
        "fresh_24h_rate": _rate(fresh_samples, valid_answers),
        "failure_rate": _rate(failed_samples, total_samples),
        "statement": statement,
        "counts": {
            "total_samples": total_samples,
            "valid_answers": valid_answers,
            "brand_mentioned_answers": brand_mentioned_answers,
            "brand_identified_answers": brand_identified_answers,
            "failed_samples": failed_samples,
            "competitor_mentions": competitor_mentions,
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
            "identified_rate": "brand_identified_answers / valid_answers（答案没点名但含地址/电话/公众号名等唯一标识；与 mention_rate 并行，不覆盖。自有域名只影响 citation_share，不参与本指标）",
            "citation_share": "brand_citations / citation_total",
            "sov": "brand_mentioned_answers / (brand_mentioned_answers + competitor_mentions)；按样本-实体提及条目计数，同一竞品在一个样本中只计一次，一个样本提及多个竞品时分别计入",
            "sentiment": "规则词典命中正/负词后按净分归为 positive/neutral/negative；kpi_eligible=false，仅作人工复核信号，不进 KPI",
            "brand_position": "仅使用 monitoring_samples.brand_list_rank（有序列表项）；正文散文的首现顺序不生成位次",
            "prompt_coverage": "covered_questions / active_questions",
            "failure_rate": "failed_samples / total_samples",
            "freshness_hours": "now - latest valid sample sampled_at",
        },
    }


def engine_health(
    db: Session,
    project_id: uuid.UUID,
    *,
    round_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> list[dict]:
    """按入口聚合真实可用性、失败率、延迟、token 与费用。

    只统计本项目样本；没有样本的入口仍然返回，状态为 `untested`，
    方便看板直接回答“哪些入口配了但没跑过、哪些缺凭据”。
    """
    task_condition = (MonitoringTask.engine_entry_id == AiEngineEntry.id) & (
        MonitoringTask.project_id == project_id
    )
    sample_condition = MonitoringSample.task_id == MonitoringTask.id
    if round_id is not None:
        task_condition = task_condition & (MonitoringTask.round_id == round_id)
    if start_at is not None:
        sample_condition = sample_condition & (MonitoringSample.sampled_at >= start_at)
    if end_at is not None:
        sample_condition = sample_condition & (MonitoringSample.sampled_at <= end_at)

    rows = db.execute(
        select(
            AiEngine,
            AiEngineEntry,
            func.count(func.distinct(MonitoringTask.id)).label("task_count"),
            func.count(MonitoringSample.id).label("sample_count"),
            func.sum(
                case(
                    (MonitoringSample.status.in_(VALID_SAMPLE_STATUSES), 1),
                    else_=0,
                )
            ).label("valid_answers"),
            func.sum(
                case((MonitoringSample.status == SampleStatus.FAILED, 1), else_=0)
            ).label("failed_count"),
            func.avg(MonitoringSample.latency_ms).label("avg_latency_ms"),
            func.sum(MonitoringSample.total_tokens).label("total_tokens"),
            func.sum(MonitoringSample.estimated_cost_cny).label("estimated_cost_cny"),
            func.max(MonitoringSample.sampled_at).label("last_sampled_at"),
        )
        .select_from(AiEngineEntry)
        .join(AiEngine, AiEngine.id == AiEngineEntry.engine_id)
        .outerjoin(MonitoringTask, task_condition)
        .outerjoin(MonitoringSample, sample_condition)
        .group_by(AiEngine.id, AiEngineEntry.id)
        .order_by(AiEngine.code, AiEngineEntry.created_at, AiEngineEntry.id)
    ).all()

    items: list[dict] = []
    for (
        engine,
        entry,
        task_count,
        sample_count,
        valid_answers,
        failed_count,
        avg_latency_ms,
        total_tokens,
        estimated_cost,
        last_sampled_at,
    ) in rows:
        samples = int(sample_count or 0)
        failed = int(failed_count or 0)
        # 无 credential_ref 也无库内密文 = 入口不需要认证；否则凭据是否可解析
        credential_configured = (
            True
            if (
                not entry.credential_ref
                and not getattr(entry, "encrypted_secret", None)
            )
            else bool(resolve_entry_secret(entry))
        )
        price_configured = (
            engine.code == "deepseek"
            and settings.deepseek_input_price_cny_per_million is not None
            and settings.deepseek_output_price_cny_per_million is not None
        )

        if not entry.is_active:
            availability = "disabled"
        elif not entry.entry_url:
            availability = "no_endpoint"
        elif not credential_configured:
            availability = "no_credentials"
        elif samples == 0:
            availability = "untested"
        elif failed == 0:
            availability = "healthy"
        elif failed < samples:
            availability = "degraded"
        else:
            availability = "failing"

        items.append(
            {
                "engine_id": str(engine.id),
                "engine_code": engine.code,
                "engine_name": engine.name,
                "entry_id": str(entry.id),
                "entry_name": entry.name,
                "protocol": _status_value(entry.protocol),
                "model_name": entry.model_name,
                "is_active": bool(engine.is_active and entry.is_active),
                "entry_url_configured": bool(entry.entry_url),
                "credential_configured": credential_configured,
                "price_configured": bool(price_configured),
                "task_count": int(task_count or 0),
                "sample_count": samples,
                "valid_answers": int(valid_answers or 0),
                "failed_count": failed,
                "failure_rate": _rate(failed, samples),
                "avg_latency_ms": (
                    round(float(avg_latency_ms), 1) if avg_latency_ms is not None else None
                ),
                "total_tokens": int(total_tokens or 0),
                "estimated_cost_cny": (
                    float(estimated_cost) if estimated_cost is not None else None
                ),
                "last_sampled_at": last_sampled_at,
                "availability": availability,
                "access_note": entry.access_note or engine.access_note,
            }
        )
    return items

def sources(
    db: Session,
    project_id: uuid.UUID,
    *,
    answer_kind: AnswerKind | None = None,
    question_type: QuestionType | str | None = None,
    limit: int = 20,
    round_id: uuid.UUID | None = None,
    engine_id: uuid.UUID | None = None,
    question_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> list[dict]:
    """信源分布：有效回答引用到的域名聚合，并标出命中发布回执的条数。

    这是"AI 从哪取证"的视角，和"我们发布渠道被引"是两个指标：
    - `citations` / `samples`：该域名被引次数与涉及样本数；
    - `brand_related`：其中被判定为品牌自有域名的条数（`brand_profiles.owned_domains`）；
    - `channel_citations`：其中命中**发布回执 URL** 的条数——只有这部分才算渠道效果。
    归不到渠道的域名留在本列表里，不再进"渠道待归类队列"。
    """
    valid = _valid_sample_scope(
        project_id,
        round_id=round_id,
        engine_id=engine_id,
        question_id=question_id,
        start_at=start_at,
        end_at=end_at,
        answer_kind=answer_kind,
        question_type=question_type,
    ).with_only_columns(MonitoringSample.id)
    rows = db.execute(
        select(
            MonitoringCitation.domain,
            func.count(MonitoringCitation.id),
            func.count(func.distinct(MonitoringCitation.sample_id)),
            func.count(MonitoringCitation.id).filter(MonitoringCitation.is_brand_related.is_(True)),
            func.count(MonitoringCitation.id).filter(MonitoringCitation.channel_id.isnot(None)),
            func.max(MonitoringSample.sampled_at),
        )
        .select_from(MonitoringCitation)
        .join(MonitoringSample, MonitoringCitation.sample_id == MonitoringSample.id)
        .where(
            MonitoringCitation.project_id == project_id,
            MonitoringSample.id.in_(valid.scalar_subquery()),
        )
        .group_by(MonitoringCitation.domain)
        .order_by(func.count(MonitoringCitation.id).desc(), MonitoringCitation.domain)
        .limit(limit)
    ).all()
    return [
        {
            "domain": domain or "",
            "citations": int(citations or 0),
            "samples": int(samples or 0),
            "brand_related": int(brand_related or 0),
            "channel_citations": int(channel_citations or 0),
            "last_sampled_at": last_seen,
        }
        for domain, citations, samples, brand_related, channel_citations, last_seen in rows
    ]