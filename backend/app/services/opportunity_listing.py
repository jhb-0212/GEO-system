"""机会中心（Opportunity）的读写口径：列表分页、负责人名与展示快照。

`api/opportunities.py` 只留校验顺序、状态迁移与审计：

- `opportunity_row`：按项目取机会，支持 `for_update`；
- `page_opportunities`：按优先级 + 创建时间排序的分页；
- `owner_names` / `payload` / `payloads`：负责人名一次批量取回，避免每行一次查询。
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ResourceMissingError
from app.models import Opportunity, User


def opportunity_row(
    db: Session,
    project_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> Opportunity:
    query = select(Opportunity).where(
        Opportunity.project_id == project_id,
        Opportunity.id == opportunity_id,
    )
    if for_update:
        query = query.with_for_update()
    row = db.scalar(query)
    if row is None:
        raise ResourceMissingError("机会不存在", code="opportunity_missing")
    return row


def page_opportunities(
    db: Session, filters, *, page: int, page_size: int
) -> tuple[list[Opportunity], int]:
    total = int(
        db.scalar(select(func.count()).select_from(Opportunity).where(*filters)) or 0
    )
    rows = db.scalars(
        select(Opportunity)
        .where(*filters)
        .order_by(Opportunity.priority_score.desc(), Opportunity.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), total


def owner_names(db: Session, rows: list[Opportunity]) -> dict:
    ids = {row.owner_id for row in rows if row.owner_id}
    if not ids:
        return {}
    return {
        user_id: display_name
        for user_id, display_name in db.execute(
            select(User.id, User.display_name).where(User.id.in_(ids))
        ).all()
    }


def payload(row: Opportunity, owner_name: str | None = None) -> dict:
    return {
        "id": str(row.id),
        "title": row.title,
        "gap_type": row.gap_type.value,
        "status": row.status.value,
        "question_id": str(row.question_id) if row.question_id else None,
        "sample_id": str(row.sample_id) if row.sample_id else None,
        "evidence_refs": row.evidence_refs or [],
        "score_factors": row.score_factors,
        "score_weights": row.score_weights,
        "priority_score": float(row.priority_score),
        "owner_id": str(row.owner_id) if row.owner_id else None,
        "owner_name": owner_name,
        "linked_content_plan_id": str(row.linked_content_plan_id)
        if row.linked_content_plan_id
        else None,
        "linked_content_item_id": str(row.linked_content_item_id)
        if row.linked_content_item_id
        else None,
        "linked_publish_task_id": str(row.linked_publish_task_id)
        if row.linked_publish_task_id
        else None,
        "notes": row.notes,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def payloads(db: Session, rows: list[Opportunity]) -> list[dict]:
    names = owner_names(db, list(rows))
    return [payload(row, names.get(row.owner_id)) for row in rows]


def payload_one(db: Session, row: Opportunity) -> dict:
    names = owner_names(db, [row])
    return payload(row, names.get(row.owner_id))
