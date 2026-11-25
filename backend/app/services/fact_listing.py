"""事实库的读取口径：事实 / 版本 / 引用声明 / 纠错任务四条分页。

`api/facts.py` 只留审批顺序、状态迁移与审计；事实取数与分页集中在这里。
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ResourceMissingError
from app.models import AnswerFactClaim, CorrectionTask, Fact, FactVersion


def fact_row(
    db: Session,
    project_id: uuid.UUID,
    fact_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> Fact:
    query = select(Fact).where(Fact.id == fact_id, Fact.project_id == project_id)
    if for_update:
        query = query.with_for_update()
    fact = db.scalar(query)
    if fact is None:
        raise ResourceMissingError("事实不存在或不属于当前项目", code="fact_missing")
    return fact


def page_facts(
    db: Session, filters, *, page: int, page_size: int
) -> tuple[list[Fact], int]:
    total = db.scalar(select(func.count()).select_from(Fact).where(*filters)) or 0
    rows = db.scalars(
        select(Fact)
        .where(*filters)
        .order_by(Fact.fact_type, Fact.fact_key, Fact.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), int(total)


def page_versions(
    db: Session, filters, *, page: int, page_size: int
) -> tuple[list[FactVersion], int]:
    total = (
        db.scalar(select(func.count()).select_from(FactVersion).where(*filters)) or 0
    )
    rows = db.scalars(
        select(FactVersion)
        .where(*filters)
        .order_by(FactVersion.version_no.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), int(total)


def page_claims(
    db: Session, filters, *, page: int, page_size: int
) -> tuple[list[AnswerFactClaim], int]:
    total = (
        db.scalar(select(func.count()).select_from(AnswerFactClaim).where(*filters))
        or 0
    )
    rows = db.scalars(
        select(AnswerFactClaim)
        .where(*filters)
        .order_by(AnswerFactClaim.created_at.desc(), AnswerFactClaim.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), int(total)


def page_corrections(
    db: Session, filters, *, page: int, page_size: int
) -> tuple[list[CorrectionTask], int]:
    total = (
        db.scalar(select(func.count()).select_from(CorrectionTask).where(*filters)) or 0
    )
    rows = db.scalars(
        select(CorrectionTask)
        .where(*filters)
        .order_by(CorrectionTask.created_at.desc(), CorrectionTask.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), int(total)
