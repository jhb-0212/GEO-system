"""跨实体 trace 串接：轮次 → 任务 → 样本 → 引用 → 内容版本 → 发布任务。

只读查询，不猜链路：trace_id 在任务/样本/引用/发布任务上分别匹配；内容版本只通过
`content_version_citations` 真正引用到本 trace 的引用才纳入。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    AiEngine,
    AiEngineEntry,
    ContentItem,
    ContentVersion,
    ContentVersionCitation,
    MonitoringCitation,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    PublishAccount,
    PublishTask,
    Question,
    QuestionVersion,
    Channel,
)


def trace_for_content_version(db: Session, version_id: uuid.UUID) -> str | None:
    """内容版本引用的监测证据 → 唯一 trace；多 trace 返回 None，不随便挑一条。"""
    rows = db.scalars(
        select(MonitoringCitation.trace_id)
        .join(
            ContentVersionCitation,
            ContentVersionCitation.citation_id == MonitoringCitation.id,
        )
        .where(
            ContentVersionCitation.version_id == version_id,
            MonitoringCitation.trace_id.is_not(None),
        )
    ).all()
    traces = {trace for trace in rows if trace}
    return next(iter(traces)) if len(traces) == 1 else None


def trace_detail(db: Session, *, project_id: uuid.UUID, trace_id: str) -> dict[str, Any]:
    """返回一条 trace 的完整只读链路；不存在时 `found=false`，不伪造节点。"""
    trace_id = trace_id.strip()
    if not trace_id:
        return _empty(trace_id)

    task_rows = db.execute(
        select(MonitoringTask, Question, QuestionVersion, AiEngine, AiEngineEntry)
        .join(QuestionVersion, QuestionVersion.id == MonitoringTask.question_version_id)
        .join(Question, Question.id == QuestionVersion.question_id)
        .join(AiEngineEntry, AiEngineEntry.id == MonitoringTask.engine_entry_id)
        .join(AiEngine, AiEngine.id == AiEngineEntry.engine_id)
        .where(
            MonitoringTask.project_id == project_id,
            MonitoringTask.trace_id == trace_id,
        )
        .order_by(MonitoringTask.created_at, MonitoringTask.id)
    ).all()

    task_ids = [task.id for task, *_ in task_rows]
    sample_rows = db.scalars(
        select(MonitoringSample)
        .where(
            MonitoringSample.project_id == project_id,
            or_(
                MonitoringSample.trace_id == trace_id,
                MonitoringSample.task_id.in_(task_ids) if task_ids else False,
            ),
        )
        .order_by(MonitoringSample.created_at, MonitoringSample.attempt_no)
    ).all()
    sample_ids = [sample.id for sample in sample_rows]

    citation_rows = db.scalars(
        select(MonitoringCitation)
        .where(
            MonitoringCitation.project_id == project_id,
            or_(
                MonitoringCitation.trace_id == trace_id,
                MonitoringCitation.sample_id.in_(sample_ids) if sample_ids else False,
            ),
        )
        .order_by(MonitoringCitation.created_at, MonitoringCitation.id)
    ).all()
    citation_ids = [citation.id for citation in citation_rows]

    version_rows = db.execute(
        select(ContentVersion, ContentItem)
        .join(ContentItem, ContentItem.id == ContentVersion.item_id)
        .join(
            ContentVersionCitation,
            ContentVersionCitation.version_id == ContentVersion.id,
        )
        .where(
            ContentVersion.project_id == project_id,
            ContentVersionCitation.citation_id.in_(citation_ids) if citation_ids else False,
        )
        .distinct()
        .order_by(ContentVersion.created_at, ContentVersion.id)
    ).all()
    version_ids = [version.id for version, _item in version_rows]

    publish_rows = db.execute(
        select(PublishTask, Channel, PublishAccount)
        .join(Channel, Channel.id == PublishTask.channel_id)
        .join(PublishAccount, PublishAccount.id == PublishTask.account_id)
        .where(
            PublishTask.project_id == project_id,
            or_(
                PublishTask.trace_id == trace_id,
                PublishTask.version_id.in_(version_ids) if version_ids else False,
            ),
        )
        .order_by(PublishTask.created_at, PublishTask.id)
    ).all()

    round_ids = (
        db.scalars(
            select(MonitoringTask.round_id)
            .where(
                MonitoringTask.project_id == project_id,
                MonitoringTask.trace_id == trace_id,
            )
            .distinct()
        ).all()
        if task_rows
        else []
    )
    round_rows = (
        db.scalars(
            select(MonitoringRound)
            .where(
                MonitoringRound.project_id == project_id,
                MonitoringRound.id.in_(round_ids),
            )
            .order_by(MonitoringRound.seq)
        ).all()
        if round_ids
        else []
    )

    if not (task_rows or sample_rows or citation_rows or version_rows or publish_rows):
        return _empty(trace_id)

    return {
        "trace_id": trace_id,
        "found": True,
        "rounds": [
            {"id": str(row.id), "seq": row.seq, "status": _value(row.status)}
            for row in round_rows
        ],
        "tasks": [
            {
                "id": str(task.id),
                "serial_no": task.serial_no,
                "round_id": str(task.round_id),
                "status": _value(task.status),
                "question_code": question.code,
                "question_title": question.title,
                "question_version_id": str(version.id),
                "version_no": version.version_no,
                "engine_code": engine.code,
                "engine_name": engine.name,
                "entry_name": entry.name,
                "sampling_mode": _value(task.sampling_mode),
            }
            for task, question, version, engine, entry in task_rows
        ],
        "samples": [
            {
                "id": str(sample.id),
                "serial_no": sample.serial_no,
                "task_id": str(sample.task_id),
                "attempt_no": sample.attempt_no,
                "status": _value(sample.status),
                "brand_mentioned": sample.brand_mentioned,
                "failure_code": _value(sample.failure_code),
                "failure_note": sample.failure_note,
                "latency_ms": sample.latency_ms,
                "total_tokens": sample.total_tokens,
                "estimated_cost_cny": (
                    float(sample.estimated_cost_cny)
                    if sample.estimated_cost_cny is not None
                    else None
                ),
                "gateway_version": sample.gateway_version,
                "sampled_at": sample.sampled_at,
            }
            for sample in sample_rows
        ],
        "citations": [
            {
                "id": str(citation.id),
                "sample_id": str(citation.sample_id),
                "domain": citation.domain,
                "raw_url": citation.raw_url,
                "title": citation.title,
                "site_name": citation.site_name,
                "snippet": citation.snippet,
                "published_at": citation.published_at,
                "is_brand_related": citation.is_brand_related,
                "citation_usage": _value(citation.citation_usage),
                "review_status": _value(citation.review_status),
            }
            for citation in citation_rows
        ],
        "content_versions": [
            {
                "id": str(version.id),
                "item_id": str(version.item_id),
                "item_title": item.title,
                "version_no": version.version_no,
                "status": _value(version.status),
                "content_hash": version.content_hash,
            }
            for version, item in version_rows
        ],
        "publish_tasks": [
            {
                "id": str(task.id),
                "serial_no": task.serial_no,
                "version_id": str(task.version_id),
                "status": _value(task.status),
                "publish_mode": _value(task.publish_mode),
                "channel_name": channel.name,
                "account_name": account.name,
                "trace_id": task.trace_id,
                "created_at": task.created_at,
            }
            for task, channel, account in publish_rows
        ],
        "counts": {
            "rounds": len(round_rows),
            "tasks": len(task_rows),
            "samples": len(sample_rows),
            "citations": len(citation_rows),
            "content_versions": len(version_rows),
            "publish_tasks": len(publish_rows),
        },
    }


def _empty(trace_id: str) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "found": False,
        "rounds": [],
        "tasks": [],
        "samples": [],
        "citations": [],
        "content_versions": [],
        "publish_tasks": [],
        "counts": {
            "rounds": 0,
            "tasks": 0,
            "samples": 0,
            "citations": 0,
            "content_versions": 0,
            "publish_tasks": 0,
        },
    }


def _value(value: object) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))
