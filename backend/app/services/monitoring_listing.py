"""监测样本 / 排障清单的分页读取。

分页与联表口径放在这里，序列化仍由 `api/monitoring.py` 的形状函数决定
（样本摘要要带证据数，排障行要带任务状态与引擎/题目）。

口径备注：
- 样本列表按 `created_at desc` 排，不是按采样时间，便于「刚补录的样本」立即可见；
- 排障清单按 `finished_at desc nulls_last`，失败的样本常常没有 `finished_at`，
  让它们沉底而不是占满第一页。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AiEngine,
    AiEngineEntry,
    EvidenceFile,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.models.enums import FailureCode, SampleStatus


def page_samples(
    db: Session,
    project_id: uuid.UUID,
    *,
    status: SampleStatus | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[MonitoringSample], dict[uuid.UUID, int]]:
    """返回 (总数, 当前页样本, 每个样本的证据文件数)。"""
    filters = [MonitoringSample.project_id == project_id]
    if status is not None:
        filters.append(MonitoringSample.status == status)

    total = int(db.scalar(select(func.count()).select_from(MonitoringSample).where(*filters)) or 0)
    rows = db.scalars(
        select(MonitoringSample)
        .where(*filters)
        .order_by(MonitoringSample.created_at.desc(), MonitoringSample.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    sample_ids = [row.id for row in rows]
    evidence_counts: dict[uuid.UUID, int] = {}
    if sample_ids:
        evidence_counts = {
            sample_id: int(count)
            for sample_id, count in db.execute(
                select(EvidenceFile.sample_id, func.count(EvidenceFile.id))
                .where(
                    EvidenceFile.project_id == project_id,
                    EvidenceFile.sample_id.in_(sample_ids),
                )
                .group_by(EvidenceFile.sample_id)
            ).all()
        }
    return total, list(rows), evidence_counts


def page_diagnostics(
    db: Session,
    project_id: uuid.UUID,
    *,
    status: SampleStatus = SampleStatus.FAILED,
    failure_code: FailureCode | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[dict[str, Any]]]:
    """排障清单：失败样本 + 任务状态 + 引擎/问题 + 重试次数/耗时/trace。"""
    filters = [
        MonitoringSample.project_id == project_id,
        MonitoringSample.status == status,
    ]
    if failure_code is not None:
        filters.append(MonitoringSample.failure_code == failure_code)

    total = int(db.scalar(select(func.count()).select_from(MonitoringSample).where(*filters)) or 0)
    rows = db.execute(
        select(MonitoringSample, MonitoringTask, Question, AiEngine)
        .join(MonitoringTask, MonitoringTask.id == MonitoringSample.task_id)
        .join(QuestionVersion, QuestionVersion.id == MonitoringTask.question_version_id)
        .join(Question, Question.id == QuestionVersion.question_id)
        .join(AiEngineEntry, AiEngineEntry.id == MonitoringTask.engine_entry_id)
        .join(AiEngine, AiEngine.id == AiEngineEntry.engine_id)
        .where(*filters)
        .order_by(
            MonitoringSample.finished_at.desc().nulls_last(),
            MonitoringSample.created_at.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items = [
        {
            "sample_id": str(sample.id),
            "serial_no": sample.serial_no,
            "task_id": str(task.id),
            "trace_id": sample.trace_id or task.trace_id,
            "sample_status": sample.status.value,
            "task_status": task.status.value,
            "attempt_no": sample.attempt_no,
            "retry_count": max(sample.attempt_no - 1, 0),
            "sampled_at": sample.sampled_at,
            "finished_at": sample.finished_at,
            "failure_code": sample.failure_code.value if sample.failure_code else None,
            "failure_note": sample.failure_note,
            "latency_ms": sample.latency_ms,
            "total_tokens": sample.total_tokens,
            "estimated_cost_cny": (
                float(sample.estimated_cost_cny)
                if sample.estimated_cost_cny is not None
                else None
            ),
            "gateway_version": sample.gateway_version,
            "engine_code": engine.code,
            "engine_name": engine.name,
            "question_code": question.code,
            "question_title": question.title,
        }
        for sample, task, question, engine in rows
    ]
    return total, items
