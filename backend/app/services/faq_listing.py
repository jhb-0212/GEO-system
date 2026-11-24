"""FAQ 台账的读取与分页，从 `api/faqs.py` 下沉。

搜索口径与 api 一致：`%` / `_` 是 LIKE 通配符，必须转义后再用 `escape="\\"` 还原为字面量。
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Faq
from app.models.enums import FaqStatus


def _apply_filters(base, category: str | None, q: str | None):
    if category:
        base = base.where(Faq.category == category)
    if q and q.strip():
        literal = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        keyword = f"%{literal}%"
        base = base.where(
            Faq.question.ilike(keyword, escape="\\") | Faq.answer.ilike(keyword, escape="\\")
        )
    return base


def page_faqs(
    db: Session,
    project_id: uuid.UUID,
    *,
    status: FaqStatus | None,
    category: str | None,
    deleted: bool | None,
    q: str | None,
    page: int,
    page_size: int,
) -> tuple[int, list[Faq]]:
    base = select(Faq).where(Faq.project_id == project_id)
    if status is not None:
        base = base.where(Faq.status == status)
    if deleted:
        base = base.where(Faq.deleted_at.is_not(None))
    else:
        base = base.where(Faq.deleted_at.is_(None))
    base = _apply_filters(base, category, q)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(Faq.sort_order, Faq.created_at)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return int(total), list(rows)


def page_review_queue(
    db: Session,
    project_id: uuid.UUID,
    *,
    category: str | None,
    q: str | None,
    page: int,
    page_size: int,
) -> tuple[int, list[Faq]]:
    """审核队列：只返回待审 FAQ，按提交/更新时间正序，先到先审。"""
    base = select(Faq).where(
        Faq.project_id == project_id,
        Faq.deleted_at.is_(None),
        Faq.status == FaqStatus.PENDING_REVIEW,
    )
    base = _apply_filters(base, category, q)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(Faq.updated_at, Faq.created_at)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return int(total), list(rows)


def faq_categories(db: Session, project_id: uuid.UUID) -> list[str]:
    rows = db.scalars(
        select(Faq.category)
        .where(
            Faq.project_id == project_id,
            Faq.deleted_at.is_(None),
            Faq.category.is_not(None),
        )
        .distinct()
        .order_by(Faq.category)
    ).all()
    return [value for value in rows if value]
