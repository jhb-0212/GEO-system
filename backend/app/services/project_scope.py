"""项目范围查询与归属校验：凡按项目读写的入口都必须经过这里，防止跨项目读取或串写。"""

import uuid
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.errors import ProjectAccessError


def scoped(model: Any, project_id: uuid.UUID) -> Select:
    """按项目范围构造查询：所有列表接口的起点。"""
    return select(model).where(model.project_id == project_id)


def scoped_where(model: Any, project_id: uuid.UUID, *conditions: Any) -> Select:
    return select(model).where(model.project_id == project_id, *conditions)


def ensure_same_project(obj: Any, project_id: uuid.UUID, *, resource: str = "resource") -> None:
    """单条记录归属校验：防止用别的项目 id 读到本不该读的对象。"""
    obj_project = getattr(obj, "project_id", None)
    if obj_project is None:
        raise ProjectAccessError(f"{resource} has no project scope")
    if uuid.UUID(str(obj_project)) != uuid.UUID(str(project_id)):
        raise ProjectAccessError(f"{resource} does not belong to this project")


def require_scoped_row(
    db: Session,
    model: Any,
    project_id: uuid.UUID,
    *,
    resource: str = "resource",
    **filters: Any,
) -> Any:
    """按 id 取单据时必须带 project_id 条件；查不到统一按越权处理，不暴露是否存在。"""
    conditions = [getattr(model, key) == value for key, value in filters.items()]
    row = db.scalar(scoped_where(model, project_id, *conditions))
    if row is None:
        raise ProjectAccessError(f"{resource} not found in this project")
    return row
