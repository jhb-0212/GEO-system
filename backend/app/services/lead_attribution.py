"""线索归因落库与查询。

只看链路事实，不推断：有监测样本就按样本的任务反查引擎与问题；有内容项就记内容项；
只有 UTM/自报来源时 confidence=low，不硬绑到某个样本。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AiEngineEntry,
    Lead,
    LeadAttribution,
    MonitoringSample,
    MonitoringTask,
    QuestionVersion,
)


def resolve_sample(db: Session, project_id: uuid.UUID, sample_id: uuid.UUID | None) -> dict[str, Any]:
    if sample_id is None:
        return {}
    sample = db.scalar(select(MonitoringSample).where(
        MonitoringSample.id == sample_id, MonitoringSample.project_id == project_id
    ))
    if sample is None:
        return {}
    task = db.scalar(select(MonitoringTask).where(MonitoringTask.id == sample.task_id))
    if task is None:
        return {"sample_id": sample.id}
    version = db.scalar(select(QuestionVersion).where(QuestionVersion.id == task.question_version_id))
    entry = db.scalar(select(AiEngineEntry).where(AiEngineEntry.id == task.engine_entry_id))
    return {
        "sample_id": sample.id,
        "question_id": version.question_id if version else None,
        "engine_id": entry.engine_id if entry else None,
        "answer_kind": sample.answer_kind.value if sample.answer_kind else None,
    }


def create_for_lead(
    db: Session, lead: Lead, *, sample_id: uuid.UUID | None = None,
    content_item_id: uuid.UUID | None = None, article_url: str | None = None,
    question_id: uuid.UUID | None = None, engine_id: uuid.UUID | None = None,
    channel_id: uuid.UUID | None = None, utm_campaign: str | None = None,
) -> LeadAttribution:
    resolved = resolve_sample(db, lead.project_id, sample_id)
    question = resolved.get("question_id") or question_id
    engine = resolved.get("engine_id") or engine_id
    if resolved.get("sample_id") and content_item_id:
        confidence, score = "high", 1.0
    elif resolved.get("sample_id") or question:
        confidence, score = "high" if resolved.get("sample_id") else "medium", 0.8 if resolved.get("sample_id") else 0.6
    elif engine or channel_id or content_item_id:
        confidence, score = "medium", 0.5
    else:
        confidence, score = "low", 0.2
    evidence = {
        key: str(value) for key, value in {
            "sample_id": resolved.get("sample_id"), "question_id": question,
            "engine_id": engine, "channel_id": channel_id, "content_item_id": content_item_id,
        }.items() if value
    }
    if utm_campaign:
        evidence["utm_campaign"] = utm_campaign
    row = LeadAttribution(
        project_id=lead.project_id, lead_id=lead.id,
        sample_id=resolved.get("sample_id"), question_id=question,
        engine_id=engine, channel_id=channel_id, content_item_id=content_item_id,
        article_url=article_url, answer_kind=resolved.get("answer_kind"),
        confidence=confidence, confidence_score=score, evidence=evidence,
    )
    db.add(row)
    db.flush()
    return row


def get_for_lead(db: Session, project_id: uuid.UUID, lead_id: uuid.UUID) -> dict[str, Any] | None:
    row = db.scalar(select(LeadAttribution).where(
        LeadAttribution.project_id == project_id,
        LeadAttribution.lead_id == lead_id,
    ))
    return payload(row) if row is not None else None


def payload(row: LeadAttribution) -> dict[str, Any]:    return {
        "lead_id": str(row.lead_id), "sample_id": str(row.sample_id) if row.sample_id else None,
        "question_id": str(row.question_id) if row.question_id else None,
        "engine_id": str(row.engine_id) if row.engine_id else None,
        "channel_id": str(row.channel_id) if row.channel_id else None,
        "content_item_id": str(row.content_item_id) if row.content_item_id else None,
        "article_url": row.article_url, "answer_kind": row.answer_kind,
        "confidence": row.confidence,
        "confidence_score": float(row.confidence_score) if row.confidence_score is not None else None,
        "evidence": row.evidence,
    }
