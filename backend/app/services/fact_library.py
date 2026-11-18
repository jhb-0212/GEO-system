"""权威事实库服务：状态机、版本快照与就业承诺强校验。

不把规则只写在接口里，版本快照、审批前置校验都在这里统一执行，避免批量脚本
或未来新入口绕过。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.models import Fact, FactVersion
from app.models.enums import FactStatus, FactVersionAction

# “保证就业/包分配”属于高风险承诺，必须由业务方书面确认才允许批准。
_GUARANTEE_TERMS = (
    "保证就业",
    "包就业",
    "包分配",
    "承诺就业",
    "确保就业",
    "100%就业",
    "百分百就业",
    "百分之百就业",
    "一定就业",
)


def has_employment_guarantee(text: str) -> bool:
    normalized = (text or "").replace(" ", "")
    return any(term in normalized for term in _GUARANTEE_TERMS)


def fact_snapshot(fact: Fact) -> dict[str, Any]:
    """完整事实快照，时间统一 ISO，便于 JSONB 审计与跨版本 diff。"""
    return {
        "fact_id": str(fact.id),
        "fact_type": fact.fact_type.value,
        "fact_key": fact.fact_key,
        "fact_value": fact.fact_value,
        "source_document": fact.source_document,
        "source_url": fact.source_url,
        "owner": fact.owner,
        "approval_status": fact.approval_status.value,
        "effective_from": fact.effective_from.isoformat() if fact.effective_from else None,
        "effective_until": fact.effective_until.isoformat() if fact.effective_until else None,
        "version_no": fact.version_no,
        "business_confirmed": fact.business_confirmed,
        "business_confirmed_note": fact.business_confirmed_note,
        "approved_by": str(fact.approved_by) if fact.approved_by else None,
        "approved_at": fact.approved_at.isoformat() if fact.approved_at else None,
        "rejection_note": fact.rejection_note,
    }


def _next_history_no(db: Session, fact_id: uuid.UUID) -> int:
    current = db.scalar(
        select(func.max(FactVersion.version_no)).where(FactVersion.fact_id == fact_id)
    )
    return int(current or 0) + 1


def append_fact_version(
    db: Session,
    fact: Fact,
    *,
    action: FactVersionAction,
    actor_id: uuid.UUID | None,
    previous_snapshot: dict[str, Any] | None = None,
    change_note: str | None = None,
) -> FactVersion:
    row = FactVersion(
        project_id=fact.project_id,
        fact_id=fact.id,
        version_no=_next_history_no(db, fact.id),
        action=action,
        snapshot=fact_snapshot(fact),
        previous_snapshot=previous_snapshot,
        change_note=change_note,
        actor_id=actor_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    return row


def ensure_approvable(fact: Fact, *, business_confirmed: bool) -> None:
    if fact.approval_status != FactStatus.PENDING_REVIEW:
        raise ConflictError("事实尚未提交审批或已处理", code="fact_review_state")
    if not (fact.source_document or "").strip() and not (fact.source_url or "").strip():
        raise ConflictError("事实缺少来源文件或来源链接，不能批准", code="fact_source_required")
    if has_employment_guarantee(fact.fact_value):
        if not business_confirmed or not fact.business_confirmed:
            raise ConflictError(
                "“保证就业/包分配”类表述缺少业务方书面确认，不能批准",
                code="employment_guarantee_unconfirmed",
            )
        if not (fact.business_confirmed_note or "").strip():
            raise ConflictError(
                "就业承诺已确认但缺少书面确认说明，不能批准",
                code="business_confirmation_note_required",
            )
