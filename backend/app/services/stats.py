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
from datetime import datetime

from sqlalchemy import case, exists, func, select
from sqlalchemy.orm import Session

from app.models import (
    AiEngine,
    AiEngineEntry,
    MonitoringCitation,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.models.enums import CitationReviewStatus, SampleStatus

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
