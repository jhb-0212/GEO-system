"""线索读取：列表分页、导出取行、负责人显示名。

列表与导出用的是同一条排序（`created_at desc`）：运营在页面上看到的最新线索，
导出的 CSV 第一行也该是同一条，否则「导出核对」永远对不上号。
所以排序与过滤只在这里定义一次。

联系方式脱敏不在这里做：它取决于当前用户的权限（`_should_mask_contact`），
属于鉴权层的决定，不属于查询层。
"""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Lead, User


def lead_total(db: Session, project_id: uuid.UUID) -> int:
    return int(
        db.scalar(select(func.count()).select_from(Lead).where(Lead.project_id == project_id))
        or 0
    )


def page_leads(
    db: Session, project_id: uuid.UUID, *, page: int = 1, page_size: int = 20
) -> tuple[int, list[Lead]]:
    total = lead_total(db, project_id)
    rows = db.scalars(
        select(Lead)
        .where(Lead.project_id == project_id)
        .order_by(Lead.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return total, list(rows)


def rows_for_export(db: Session, project_id: uuid.UUID, limit: int) -> list[Lead]:
    return list(
        db.scalars(
            select(Lead)
            .where(Lead.project_id == project_id)
            .order_by(Lead.created_at.desc())
            .limit(limit)
        ).all()
    )


def owner_names(db: Session, rows: Sequence[Lead]) -> dict[uuid.UUID, str]:
    """一次取回本页涉及的负责人名称。"""
    owner_ids = [row.owner_id for row in rows if row.owner_id]
    if not owner_ids:
        return {}
    return {
        user_id: (display_name or username)
        for user_id, display_name, username in db.execute(
            select(User.id, User.display_name, User.username).where(
                User.id.in_(owner_ids)
            )
        ).all()
    }
