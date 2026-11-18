"""每轮统计快照：把范围、分母、指标与规则版本一起冻结，保证历史可比。

快照只在显式调用时创建；同一轮只允许一份，重复冻结返回冲突，不覆盖历史结果。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ResourceMissingError
from app.models import (
    AiEngine,
    AiEngineEntry,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
    StatSnapshot,
)
from app.models.enums import AnswerKind, QuestionType
from app.services.monitoring_extraction import MATCHER_VERSION
from app.services.citation_classification import CLASSIFIER_VERSION
from app.services.stats import by_engine, by_question, geo_overview, overview, overview_by_answer_kind, sources

STAT_RULE_VERSION = "stat-snapshot-v1"


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _scope(db: Session, project_id: uuid.UUID, round_row: MonitoringRound) -> dict[str, Any]:
    versions = db.execute(
        select(
            QuestionVersion.id,
            QuestionVersion.question_id,
            QuestionVersion.text,
            QuestionVersion.question_type,
            Question.code,
            Question.title,
        )
        .join(Question, QuestionVersion.question_id == Question.id)
        .join(MonitoringTask, MonitoringTask.question_version_id == QuestionVersion.id)
        .where(
            QuestionVersion.project_id == project_id,
            MonitoringTask.project_id == project_id,
            MonitoringTask.round_id == round_row.id,
        )
        .distinct()
    ).all()
    entries = db.execute(
        select(AiEngineEntry.id, AiEngineEntry.name, AiEngine.code, AiEngine.name)
        .join(AiEngine, AiEngineEntry.engine_id == AiEngine.id)
        .join(MonitoringTask, MonitoringTask.engine_entry_id == AiEngineEntry.id)
        .where(
            MonitoringTask.project_id == project_id,
            MonitoringTask.round_id == round_row.id,
        )
        .distinct()
    ).all()
    modes = db.scalars(
        select(MonitoringTask.sampling_mode)
        .where(
            MonitoringTask.project_id == project_id,
            MonitoringTask.round_id == round_row.id,
        )
        .distinct()
    ).all()
    sampled = db.execute(
        select(func.min(MonitoringSample.sampled_at), func.max(MonitoringSample.sampled_at)).where(
            MonitoringSample.project_id == project_id,
            MonitoringSample.task_id.in_(
                select(MonitoringTask.id).where(
                    MonitoringTask.project_id == project_id,
                    MonitoringTask.round_id == round_row.id,
                )
            ),
        )
    ).one()
    return {
        "round": {
            "id": str(round_row.id),
            "seq": round_row.seq,
            "name": round_row.name,
            "status": round_row.status.value,
            "is_baseline": round_row.is_baseline,
        },
        "round_snapshot": {
            "analysis_config_snapshot": round_row.analysis_config_snapshot,
            "analysis_config_hash": round_row.analysis_config_hash,
            "analysis_config_version": round_row.analysis_config_version,
            "captured_at": round_row.analysis_config_captured_at,
        },
        "question_versions": [
            {
                "id": str(row.id),
                "question_id": str(row.question_id),
                "question_code": row.code,
                "question_title": row.title,
                "text": row.text,
                "question_type": row.question_type.value if row.question_type else None,
            }
            for row in versions
        ],
        "engine_entries": [
            {
                "id": str(row.id),
                "name": row.name,
                "engine_code": row[2],
                "engine_name": row[3],
            }
            for row in entries
        ],
        "sampling_modes": [mode.value if hasattr(mode, "value") else str(mode) for mode in modes],
        "window": {
            "sampled_from": sampled[0].isoformat() if sampled[0] else None,
            "sampled_to": sampled[1].isoformat() if sampled[1] else None,
        },
        "rule_versions": {
            "stats": STAT_RULE_VERSION,
            "matcher": MATCHER_VERSION,
            "classifier": CLASSIFIER_VERSION,
        },
    }


def _metrics(db: Session, project_id: uuid.UUID, round_id: uuid.UUID) -> dict[str, Any]:
    return {
        "overview": overview(db, project_id, round_id=round_id),
        "overview_by_answer_kind": overview_by_answer_kind(db, project_id, round_id=round_id),
        "overview_general": overview(
            db, project_id, round_id=round_id, question_type=QuestionType.GENERAL
        ),
        "overview_brand": overview(
            db, project_id, round_id=round_id, question_type=QuestionType.BRAND
        ),
        "by_engine": by_engine(db, project_id, round_id=round_id),
        "by_question": by_question(db, project_id, round_id=round_id),
        "geo": geo_overview(db, project_id, round_id=round_id),
        "sources": sources(db, project_id, round_id=round_id, limit=200),
        "denominators": {
            "valid_answers": overview(db, project_id, round_id=round_id)["valid_answers"],
            "answer_kind": {
                kind.value: item["valid_answers"]
                for kind, item in zip(
                    (AnswerKind.ANSWER, AnswerKind.SEARCH_RESULT),
                    overview_by_answer_kind(db, project_id, round_id=round_id),
                )
            },
        },
    }


def snapshot_hash(scope: dict[str, Any], metrics: dict[str, Any]) -> str:
    payload = json.dumps(
        {"scope": scope, "metrics": metrics},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def create_round_snapshot(
    db: Session, project_id: uuid.UUID, round_id: uuid.UUID, actor_id: uuid.UUID | None
) -> StatSnapshot:
    round_row = db.get(MonitoringRound, round_id)
    if round_row is None or round_row.project_id != project_id:
        raise ResourceMissingError("监测轮次不存在")
    existing = db.scalar(
        select(StatSnapshot).where(
            StatSnapshot.project_id == project_id,
            StatSnapshot.round_id == round_id,
        )
    )
    if existing is not None:
        raise ConflictError("该轮次已冻结统计快照", code="snapshot_exists")

    scope = _scope(db, project_id, round_row)
    metrics = _metrics(db, project_id, round_id)
    scope = _jsonable(scope)
    metrics = _jsonable(metrics)
    digest = snapshot_hash(scope, metrics)
    snapshot = StatSnapshot(
        project_id=project_id,
        round_id=round_id,
        captured_by=actor_id,
        captured_at=datetime.now(timezone.utc),
        scope=_jsonable(scope),
        metrics=_jsonable(metrics),
        definitions={
            "stats": STAT_RULE_VERSION,
            "matcher": MATCHER_VERSION,
            "classifier": CLASSIFIER_VERSION,
        },
        rule_version=STAT_RULE_VERSION,
        matcher_version=MATCHER_VERSION,
        classifier_version=CLASSIFIER_VERSION,
        snapshot_hash=digest,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def snapshot_payload(row: StatSnapshot) -> dict[str, Any]:
    return {
        "snapshot_id": str(row.id),
        "round_id": str(row.round_id),
        "captured_at": row.captured_at,
        "captured_by": str(row.captured_by) if row.captured_by else None,
        "rule_version": row.rule_version,
        "matcher_version": row.matcher_version,
        "classifier_version": row.classifier_version,
        "snapshot_hash": row.snapshot_hash,
        "scope": row.scope,
        "metrics": row.metrics,
        "definitions": row.definitions,
    }
