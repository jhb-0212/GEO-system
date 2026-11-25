"""只读 API/MCP 的数据查询；API 层不直接 select。"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApiKey, MonitoringSample, Opportunity, Question
from app.services import api_keys, stats


def overview(db: Session, project_id: uuid.UUID) -> dict[str, Any]:
    return stats.overview(db, project_id)


def questions(db: Session, project_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = db.scalars(select(Question).where(Question.project_id == project_id).order_by(
        Question.priority.desc(), Question.created_at
    )).all()
    return [{
        "id": str(row.id), "code": row.code, "title": row.title,
        "question_type": row.question_type.value, "status": row.status.value,
        "priority": row.priority, "current_version_no": row.current_version_no,
    } for row in rows]


def samples(db: Session, project_id: uuid.UUID, limit: int) -> list[dict[str, Any]]:
    rows = db.scalars(select(MonitoringSample).where(
        MonitoringSample.project_id == project_id
    ).order_by(MonitoringSample.sampled_at.desc()).limit(limit)).all()
    return [{
        "id": str(row.id), "task_id": str(row.task_id),
        "sampled_at": row.sampled_at.isoformat() if row.sampled_at else None,
        "status": row.status.value, "answer_kind": row.answer_kind.value,
        "brand_mentioned": row.brand_mentioned, "brand_identified": row.brand_identified,
        "brand_recommendation": row.brand_recommendation, "brand_list_rank": row.brand_list_rank,
        "entity_mention_count": row.entity_mention_count,
    } for row in rows]


def opportunities(db: Session, project_id: uuid.UUID, limit: int) -> list[dict[str, Any]]:
    rows = db.scalars(select(Opportunity).where(
        Opportunity.project_id == project_id
    ).order_by(Opportunity.priority_score.desc()).limit(limit)).all()
    return [{
        "id": str(row.id), "title": row.title, "gap_type": row.gap_type.value,
        "status": row.status.value, "priority_score": row.priority_score,
        "question_id": str(row.question_id) if row.question_id else None,
    } for row in rows]


def list_keys(db: Session, project_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = db.scalars(select(ApiKey).where(ApiKey.project_id == project_id).order_by(
        ApiKey.created_at.desc()
    )).all()
    return [api_keys.key_payload(row) for row in rows]


def find_key(db: Session, project_id: uuid.UUID, key_id: uuid.UUID) -> ApiKey | None:
    return db.scalar(select(ApiKey).where(ApiKey.id == key_id, ApiKey.project_id == project_id))
