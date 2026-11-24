"""引用明细的读取口径：列表分页，以及「AI 回答来源」选项的 trace 归组。

`answer_options` 是内容版本关联的前置选择器：一条 trace（一次提问的一次回答）出一个选项，
该 trace 下的所有引用 ID 一起提交给版本关联接口 —— 这样不新增第二套关联模型。

为什么放 service：分组逻辑（trace 兜底顺序 `citation.trace_id → sample.trace_id → task.trace_id`）
一旦只存在于某个 HTTP 函数里，别的入口想复用就会各写一份，分组口径立刻分叉。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, or_, select
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
from app.models.enums import CitationReviewStatus
from app.services.excerpts import excerpt

# 候选行上限：先取最近若干条引用再在内存里按 trace 分组，避免按 trace 做 N+1 查询。
ANSWER_OPTION_SCAN_LIMIT = 300


def page_citations(
    db: Session,
    project_id: uuid.UUID,
    *,
    review_status: CitationReviewStatus | None = None,
    sample_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[MonitoringCitation]]:
    filters = [MonitoringCitation.project_id == project_id]
    if review_status is not None:
        filters.append(MonitoringCitation.review_status == review_status)
    if sample_id is not None:
        filters.append(MonitoringCitation.sample_id == sample_id)

    total = int(
        db.scalar(select(func.count()).select_from(MonitoringCitation).where(*filters)) or 0
    )
    rows = db.scalars(
        select(MonitoringCitation)
        .where(*filters)
        .order_by(MonitoringCitation.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return total, list(rows)


def answer_options(
    db: Session,
    project_id: uuid.UUID,
    *,
    q: str | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """按 trace 归组的回答来源选项（最多 `limit` 组）。"""
    stmt = (
        select(
            MonitoringCitation,
            MonitoringSample,
            MonitoringTask,
            Question,
            QuestionVersion,
            AiEngine,
            AiEngineEntry,
        )
        .join(MonitoringSample, MonitoringSample.id == MonitoringCitation.sample_id)
        .join(MonitoringTask, MonitoringTask.id == MonitoringSample.task_id)
        .join(QuestionVersion, QuestionVersion.id == MonitoringTask.question_version_id)
        .join(Question, Question.id == QuestionVersion.question_id)
        .join(AiEngineEntry, AiEngineEntry.id == MonitoringTask.engine_entry_id)
        .join(AiEngine, AiEngine.id == AiEngineEntry.engine_id)
        .where(MonitoringCitation.project_id == project_id)
        .where(
            func.coalesce(
                MonitoringCitation.trace_id,
                MonitoringSample.trace_id,
                MonitoringTask.trace_id,
            ).is_not(None)
        )
        .order_by(MonitoringCitation.created_at.desc(), MonitoringCitation.id)
        .limit(ANSWER_OPTION_SCAN_LIMIT)
    )
    term = (q or "").strip()
    if term:
        pattern = f"%{term}%"
        stmt = stmt.where(
            or_(
                Question.title.ilike(pattern),
                QuestionVersion.text.ilike(pattern),
                MonitoringSample.raw_answer.ilike(pattern),
                MonitoringCitation.title.ilike(pattern),
                MonitoringCitation.domain.ilike(pattern),
                AiEngine.name.ilike(pattern),
                AiEngineEntry.name.ilike(pattern),
            )
        )

    groups: dict[str, dict[str, Any]] = {}
    for citation, sample, task, question, question_version, engine, entry in db.execute(stmt):
        trace_id = citation.trace_id or sample.trace_id or task.trace_id
        if not trace_id:
            continue
        group = groups.get(trace_id)
        if group is None:
            group = {
                "trace_id": trace_id,
                "question_title": question.title,
                "question_text": question_version.text,
                "engine_name": engine.name,
                "entry_name": entry.name,
                "answer_excerpt": excerpt(sample.raw_answer, 160, ellipsis=False),
                "sampled_at": sample.sampled_at or citation.created_at,
                "citation_ids": [],
                "domains": [],
            }
            groups[trace_id] = group
        group["citation_ids"].append(str(citation.id))
        if citation.domain and citation.domain not in group["domains"]:
            group["domains"].append(citation.domain)

    options: list[dict[str, Any]] = []
    for group in groups.values():
        group["citation_ids"] = list(dict.fromkeys(group["citation_ids"]))
        group["citation_count"] = len(group["citation_ids"])
        group["domains"] = group["domains"][:3]
        options.append(group)
        if len(options) >= limit:
            break
    return options
