"""原始回答快照：存档、读取、漂移比对。

三条边界：

1. **追加即冻结**。同一采样第二次存档返回既有记录（`created=False`），绝不覆盖；
   想改口径就存新样本，不改旧快照。
2. **漂移只比对纯回答**。`answer_hash` 只覆盖 `raw_answer` 文本，引用清单/复核状态变了
   不算漂移——那些本来就是后续复核会改的东西。
3. **快照不进指标**。它不参与提及率、引用率、覆盖率、分级的任何分母，只用于复核与离线重跑。
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
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
from app.models.snapshot import AnswerSnapshot


class SnapshotError(Exception):
    """调用方需要翻译成业务错误码的失败。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _canonical(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _answer_hash(raw_answer: str | None) -> str:
    return _sha256((raw_answer or "").strip())


def build_payload(db: Session, sample: MonitoringSample) -> dict:
    task = db.get(MonitoringTask, sample.task_id)
    question_code = None
    question_title = None
    question_text = None
    if task is not None:
        version = db.get(QuestionVersion, task.question_version_id)
        if version is not None:
            question_text = version.text
            question = db.get(Question, version.question_id)
            if question is not None:
                question_code = question.code
                question_title = question.title
    entry = db.get(AiEngineEntry, task.engine_entry_id) if task is not None else None
    engine = db.get(AiEngine, entry.engine_id) if entry is not None else None

    citations = db.scalars(
        select(MonitoringCitation)
        .where(MonitoringCitation.sample_id == sample.id)
        .order_by(MonitoringCitation.raw_url)
    ).all()

    return {
        "sample": {
            "id": str(sample.id),
            "serial_no": sample.serial_no,
            "attempt_no": sample.attempt_no,
            "status": str(sample.status),
            "sampled_at": sample.sampled_at.isoformat() if sample.sampled_at else None,
            "conversation_id": sample.conversation_id,
            "trace_id": sample.trace_id,
            "brand_mentioned": sample.brand_mentioned,
            "answer_kind": str(sample.answer_kind) if sample.answer_kind else None,
        },
        "question": {
            "code": question_code,
            "title": question_title,
            "text": question_text,
        },
        "engine": {
            "entry_name": entry.name if entry is not None else None,
            "code": engine.code if engine is not None else None,
            "name": engine.name if engine is not None else None,
            "supports_citation": engine.supports_citation if engine is not None else None,
        },
        "answer": {
            "raw_answer": sample.raw_answer,
            "raw_response": sample.raw_response,
        },
        "citations": [
            {
                "raw_url": citation.raw_url,
                "domain": citation.domain,
                "page_type": str(citation.page_type),
                "source_category": str(citation.source_category),
                "competitor_id": str(citation.competitor_id) if citation.competitor_id else None,
                "review_status": str(citation.review_status),
            }
            for citation in citations
        ],
    }


def capture(db: Session, project_id: uuid.UUID, sample_id: uuid.UUID) -> tuple[AnswerSnapshot, bool]:
    """存档一条样本；已存过则原样返回既有快照。"""
    existing = db.scalar(
        select(AnswerSnapshot).where(
            AnswerSnapshot.project_id == project_id,
            AnswerSnapshot.sample_id == sample_id,
        )
    )
    if existing is not None:
        return existing, False

    sample = db.scalar(
        select(MonitoringSample).where(
            MonitoringSample.project_id == project_id,
            MonitoringSample.id == sample_id,
        )
    )
    if sample is None:
        raise SnapshotError("sample_not_found", "样本不存在或不属于当前项目")
    if not (sample.raw_answer or "").strip() and not sample.raw_response:
        raise SnapshotError("sample_no_answer", "该样本没有原始回答内容，无法存档")

    payload = build_payload(db, sample)
    snapshot = AnswerSnapshot(
        project_id=project_id,
        sample_id=sample.id,
        payload=payload,
        content_hash=_sha256(_canonical(payload)),
        answer_hash=_answer_hash(sample.raw_answer),
        captured_at=datetime.now(UTC),
    )
    db.add(snapshot)
    db.flush()
    return snapshot, True


def capture_batch(db: Session, project_id: uuid.UUID, *, limit: int = 50) -> dict:
    """给最近还没存档的样本批量补档；没有回答内容的样本记入 missing。"""
    candidates = db.scalars(
        select(MonitoringSample)
        .where(
            MonitoringSample.project_id == project_id,
            ~MonitoringSample.id.in_(
                select(AnswerSnapshot.sample_id).where(AnswerSnapshot.project_id == project_id)
            ),
        )
        .order_by(MonitoringSample.sampled_at.desc().nullslast(), MonitoringSample.serial_no.desc())
        .limit(limit)
    ).all()

    captured = 0
    missing = 0
    for sample in candidates:
        if not (sample.raw_answer or "").strip() and not sample.raw_response:
            missing += 1
            continue
        capture(db, project_id, sample.id)
        captured += 1
    return {"candidates": len(candidates), "captured": captured, "missing_answer": missing}


def drift(db: Session, snapshot: AnswerSnapshot) -> bool:
    """当前 `raw_answer` 与存档时是否已不一致（只比回答文本）。"""
    sample = db.get(MonitoringSample, snapshot.sample_id)
    if sample is None:
        return False
    return _answer_hash(sample.raw_answer) != snapshot.answer_hash


def summary(db: Session, snapshot: AnswerSnapshot, *, include_drift: bool = True) -> dict:
    payload = snapshot.payload or {}
    meta = payload.get("sample") or {}
    answer = payload.get("answer") or {}
    question = payload.get("question") or {}
    engine = payload.get("engine") or {}
    return {
        "id": str(snapshot.id),
        "sample_id": str(snapshot.sample_id),
        "sample_serial_no": meta.get("serial_no"),
        "question_code": question.get("code"),
        "question_title": question.get("title"),
        "engine_name": engine.get("name") or engine.get("entry_name"),
        "answer_chars": len((answer.get("raw_answer") or "")),
        "citation_count": len(payload.get("citations") or []),
        "answer_hash": snapshot.answer_hash,
        "content_hash": snapshot.content_hash,
        "captured_at": snapshot.captured_at.isoformat() if snapshot.captured_at else None,
        "answer_drift": drift(db, snapshot) if include_drift else None,
    }


def list_snapshots(db: Session, project_id: uuid.UUID, *, limit: int = 50, offset: int = 0) -> list[dict]:
    rows = db.scalars(
        select(AnswerSnapshot)
        .where(AnswerSnapshot.project_id == project_id)
        .order_by(AnswerSnapshot.captured_at.desc(), AnswerSnapshot.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [summary(db, row) for row in rows]


def count_snapshots(db: Session, project_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(AnswerSnapshot)
            .where(AnswerSnapshot.project_id == project_id)
        )
        or 0
    )


def get_snapshot(db: Session, project_id: uuid.UUID, snapshot_id: uuid.UUID) -> dict:
    row = db.scalar(
        select(AnswerSnapshot).where(
            AnswerSnapshot.project_id == project_id,
            AnswerSnapshot.id == snapshot_id,
        )
    )
    if row is None:
        raise SnapshotError("snapshot_not_found", "快照不存在或不属于当前项目")
    return {**summary(db, row), "payload": row.payload}
