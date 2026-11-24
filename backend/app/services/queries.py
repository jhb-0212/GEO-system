"""通用取数原语：让 api 层不再自己拼 `select()`。

刻意保持极简（等值过滤 + 可选外挂条件），复杂联表仍然在各自的
领域 service 里实现；这里只接掉「按主键读一行 / 判断存在 / 简单计数」
这类重复劳动。

约定：`**eq` 是等值条件（列名或表达式名 → 值），`filters` 是额外条件列表。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session


def fetch_one(db: Session, model: Any, **eq: Any) -> Any | None:
    return db.scalar(select(model).where(*(getattr(model, key) == value for key, value in eq.items())))


def fetch_one_for_update(db: Session, model: Any, **eq: Any) -> Any | None:
    stmt = select(model).where(*(getattr(model, key) == value for key, value in eq.items()))
    return db.scalar(stmt.with_for_update())


def exists(db: Session, model: Any, **eq: Any) -> bool:
    stmt = select(model).where(*(getattr(model, key) == value for key, value in eq.items()))
    return db.scalar(stmt.limit(1)) is not None


def fetch_many(
    db: Session,
    model: Any,
    filters: list | tuple = (),
    *,
    order_by: Any = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[Any]:
    stmt = select(model)
    if filters:
        stmt = stmt.where(*filters)
    if order_by is not None:
        # 允许传单个表达式或元组，内部统一展开
        if isinstance(order_by, (list, tuple)):
            stmt = stmt.order_by(*order_by)
        else:
            stmt = stmt.order_by(order_by)
    if offset is not None:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(db.scalars(stmt).all())


def count_rows(db: Session, model: Any, filters: list | tuple = ()) -> int:
    stmt = select(func.count()).select_from(model)
    if filters:
        stmt = stmt.where(*filters)
    return int(db.scalar(stmt) or 0)


def page_of(
    db: Session,
    model: Any,
    filters: list | tuple,
    *,
    order_by: Any,
    page: int,
    page_size: int,
) -> tuple[int, list[Any]]:
    """最常见的「计数 + 一页」组合。"""
    total = count_rows(db, model, filters)
    rows = fetch_many(
        db,
        model,
        filters,
        order_by=order_by,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return total, rows
