"""内容版本的关联集合：题目、监测引用、权威事实。

三张关联表一起构成「这篇稿引用了哪些问题/证据/事实」，读和写必须同源——
以前 GET links 与 PUT links 各写一遍查询，改一处忘另一处就会出现「保存成功但读回来是空的」。

事实行的「过期/待审批/已修订」判定（`fact_link_warning`）也在本模块，
它是关联读出来的展示口径，不属于某个 HTTP 接口。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ContentVersion,
    ContentVersionCitation,
    ContentVersionFact,
    ContentVersionQuestion,
    Fact,
    MonitoringCitation,
    Question,
)
from app.models.enums import FactStatus
from app.core.errors import ResourceMissingError


def fact_link_warning(fact: Fact, linked_version_no: int, now: datetime) -> str | None:
    """这条事实关联能不能用；返回可直接展示的原因，None 表示可用。"""
    if fact.approval_status == FactStatus.DRAFT:
        return "事实未批准"
    if fact.approval_status == FactStatus.PENDING_REVIEW:
        return "事实待审批"
    if fact.approval_status == FactStatus.EXPIRED:
        return "事实已过期"
    if fact.effective_until is not None and fact.effective_until <= now:
        return "事实已过期"
    if fact.effective_from is not None and fact.effective_from > now:
        return "事实尚未生效"
    if fact.superseded_by is not None:
        return "事实已被新事实替代"
    if fact.version_no != linked_version_no:
        return f"事实已修订（关联 v{linked_version_no}，当前 v{fact.version_no}），需重新确认"
    return None


def version_links(db: Session, version_id: uuid.UUID) -> dict[str, Any]:
    """版本级关联集合：题目、监测引用与权威事实分别来自三张关联表。"""
    question_ids = db.scalars(
        select(ContentVersionQuestion.question_id)
        .where(ContentVersionQuestion.version_id == version_id)
        .order_by(ContentVersionQuestion.question_id)
    ).all()
    citation_ids = db.scalars(
        select(ContentVersionCitation.citation_id)
        .where(ContentVersionCitation.version_id == version_id)
        .order_by(ContentVersionCitation.citation_id)
    ).all()
    now = datetime.now(timezone.utc)
    fact_rows = db.execute(
        select(ContentVersionFact, Fact)
        .join(Fact, Fact.id == ContentVersionFact.fact_id)
        .where(ContentVersionFact.version_id == version_id)
        .order_by(ContentVersionFact.fact_id)
    ).all()
    fact_links = []
    for link, fact in fact_rows:
        warning = fact_link_warning(fact, link.fact_version_no, now)
        fact_links.append(
            {
                "fact_id": str(fact.id),
                "fact_type": fact.fact_type.value,
                "fact_key": fact.fact_key,
                "fact_value": fact.fact_value,
                "approval_status": fact.approval_status.value,
                "current_version_no": fact.version_no,
                "linked_version_no": link.fact_version_no,
                "stale": warning is not None,
                "warning": warning,
            }
        )
    return {
        "version_id": str(version_id),
        "question_ids": [str(row) for row in question_ids],
        "citation_ids": [str(row) for row in citation_ids],
        "fact_ids": [link["fact_id"] for link in fact_links],
        "fact_links": fact_links,
    }


def _require_all(rows: Iterable, expected: set[uuid.UUID], message: str) -> dict[uuid.UUID, Any]:
    found = {row.id: row for row in rows}
    if set(found) != expected:
        raise ResourceMissingError(message)
    return found


def resolve_targets(
    db: Session,
    project_id: uuid.UUID,
    *,
    question_ids: list[uuid.UUID],
    citation_ids: list[uuid.UUID],
    fact_ids: list[uuid.UUID],
) -> dict[uuid.UUID, Fact]:
    """校验要挂的题目/引用/事实都在本项目，返回事实字典供后续比对版本号。"""
    if question_ids:
        _require_all(
            db.scalars(
                select(Question).where(
                    Question.project_id == project_id,
                    Question.id.in_(question_ids),
                )
            ).all(),
            set(question_ids),
            "题目不存在或不属于本项目",
        )
    if citation_ids:
        _require_all(
            db.scalars(
                select(MonitoringCitation).where(
                    MonitoringCitation.project_id == project_id,
                    MonitoringCitation.id.in_(citation_ids),
                )
            ).all(),
            set(citation_ids),
            "引用证据不存在或不属于本项目",
        )
    if not fact_ids:
        return {}
    return _require_all(
        db.scalars(
            select(Fact).where(
                Fact.project_id == project_id,
                Fact.id.in_(fact_ids),
            )
        ).all(),
        set(fact_ids),
        "事实不存在或不属于本项目",
    )


def apply_links(
    db: Session,
    project_id: uuid.UUID,
    version: ContentVersion,
    *,
    question_ids: list[uuid.UUID],
    citation_ids: list[uuid.UUID],
    fact_ids: list[uuid.UUID],
    facts_by_id: dict[uuid.UUID, Fact],
    confirm_fact_revisions: bool,
) -> list[str]:
    """整版替换关联，返回被确认修订的事实 id（审计用）。

    事实修订只有显式确认才推进关联版本号；普通保存不动，避免静默把旧稿「续命」。
    """
    question_rows = db.scalars(
        select(ContentVersionQuestion).where(
            ContentVersionQuestion.version_id == version.id
        )
    ).all()
    existing_questions = {row.question_id for row in question_rows}
    desired_questions = set(question_ids)
    for row in question_rows:
        if row.question_id not in desired_questions:
            db.delete(row)
    for question_id in desired_questions - existing_questions:
        db.add(
            ContentVersionQuestion(
                project_id=project_id,
                version_id=version.id,
                question_id=question_id,
            )
        )

    citation_rows = db.scalars(
        select(ContentVersionCitation).where(
            ContentVersionCitation.version_id == version.id
        )
    ).all()
    existing_citations = {row.citation_id for row in citation_rows}
    desired_citations = set(citation_ids)
    for row in citation_rows:
        if row.citation_id not in desired_citations:
            db.delete(row)
    for citation_id in desired_citations - existing_citations:
        db.add(
            ContentVersionCitation(
                project_id=project_id,
                version_id=version.id,
                citation_id=citation_id,
            )
        )

    fact_rows = db.scalars(
        select(ContentVersionFact).where(ContentVersionFact.version_id == version.id)
    ).all()
    existing_facts = {row.fact_id: row for row in fact_rows}
    desired_facts = set(fact_ids)
    for fact_id, row in existing_facts.items():
        if fact_id not in desired_facts:
            db.delete(row)
    confirmed_revisions: list[str] = []
    for fact_id in desired_facts:
        fact = facts_by_id[fact_id]
        row = existing_facts.get(fact_id)
        if row is None:
            db.add(
                ContentVersionFact(
                    project_id=project_id,
                    version_id=version.id,
                    fact_id=fact_id,
                    fact_version_no=fact.version_no,
                )
            )
        elif row.fact_version_no != fact.version_no and confirm_fact_revisions:
            row.fact_version_no = fact.version_no
            confirmed_revisions.append(str(fact_id))
    return confirmed_revisions
