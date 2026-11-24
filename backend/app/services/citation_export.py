"""引用明细导出的联表语句与来源归类回填的批量读。

`api/citations.py` 只留参数解析、审计与同步上限校验：

- `export_statement`：引用 → 样本 → 任务 → 引擎 → 题目 的联表，导出列与筛选集中一处；
- `source_reviews_for_update` / `citations_by_domain` / `citations_by_domains`：
  域名归类时按域名批量回填引用，避免逐条查。
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AiEngine,
    AiEngineEntry,
    CitationSourceReview,
    MonitoringCitation,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.models.enums import CitationReviewStatus


def export_filters(
    project_id: uuid.UUID,
    *,
    engine_id: uuid.UUID | None,
    question_id: uuid.UUID | None,
    review_status: CitationReviewStatus | None,
    start_at: datetime | None,
    end_at: datetime | None,
) -> list:
    filters = [MonitoringCitation.project_id == project_id]
    if engine_id is not None:
        filters.append(AiEngine.id == engine_id)
    if question_id is not None:
        filters.append(Question.id == question_id)
    if review_status is not None:
        filters.append(MonitoringCitation.review_status == review_status)
    if start_at is not None:
        filters.append(MonitoringSample.sampled_at >= start_at)
    if end_at is not None:
        filters.append(MonitoringSample.sampled_at <= end_at)
    return filters


def export_statement(
    project_id: uuid.UUID,
    *,
    engine_id: uuid.UUID | None,
    question_id: uuid.UUID | None,
    review_status: CitationReviewStatus | None,
    start_at: datetime | None,
    end_at: datetime | None,
):
    return (
        select(
            MonitoringCitation,
            MonitoringSample.sampled_at,
            AiEngine.code.label("engine_code"),
            AiEngine.name.label("engine_name"),
            AiEngineEntry.name.label("entry_name"),
            Question.code.label("question_code"),
            Question.title.label("question_title"),
        )
        .join(MonitoringSample, MonitoringCitation.sample_id == MonitoringSample.id)
        .join(MonitoringTask, MonitoringSample.task_id == MonitoringTask.id)
        .join(AiEngineEntry, MonitoringTask.engine_entry_id == AiEngineEntry.id)
        .join(AiEngine, AiEngineEntry.engine_id == AiEngine.id)
        .join(
            QuestionVersion,
            MonitoringTask.question_version_id == QuestionVersion.id,
        )
        .join(Question, QuestionVersion.question_id == Question.id)
        .where(
            *export_filters(
                project_id,
                engine_id=engine_id,
                question_id=question_id,
                review_status=review_status,
                start_at=start_at,
                end_at=end_at,
            )
        )
    )


def source_reviews_for_update(
    db: Session, project_id: uuid.UUID, review_ids: list[uuid.UUID]
) -> list[CitationSourceReview]:
    return list(
        db.scalars(
            select(CitationSourceReview)
            .where(
                CitationSourceReview.project_id == project_id,
                CitationSourceReview.id.in_(review_ids),
            )
            .with_for_update()
        ).all()
    )


def citations_by_domain(
    db: Session, project_id: uuid.UUID, domain: str
) -> list[MonitoringCitation]:
    return list(
        db.scalars(
            select(MonitoringCitation).where(
                MonitoringCitation.project_id == project_id,
                MonitoringCitation.domain == domain,
            )
        ).all()
    )


def citations_by_domains(
    db: Session, project_id: uuid.UUID, domains: list[str]
) -> list[MonitoringCitation]:
    if not domains:
        return []
    return list(
        db.scalars(
            select(MonitoringCitation).where(
                MonitoringCitation.project_id == project_id,
                MonitoringCitation.domain.in_(domains),
            )
        ).all()
    )
