"""跨表引用校验：把「这个 id 属于当前项目吗」统一成一处。

以前每个 api 文件自己写一遍 `db.scalar(select(X.id).where(...)) is None`，既重复
也容易漏掉 project_id。这里给一组按语义命名的薄封装，返回同一套 404 语义：

- `require_project_row_id`：普通业务表按 `project_id + id` 校验；
- `require_member`：负责人必须是当前项目的有效成员（按 `user_id` 校验）；
- `user_display_name`：单个用户显示名，取不到返回 None。
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ResourceMissingError
from app.models import ProjectMember, User


def require_project_row_id(
    db: Session,
    model,
    project_id: uuid.UUID,
    value: uuid.UUID | None,
    *,
    label: str,
    code: str,
) -> None:
    """`value` 为空表示该关联可空，直接放行；否则必须存在且属于本项目。"""
    if value is None:
        return
    row = db.scalar(select(model.id).where(model.project_id == project_id, model.id == value))
    if row is None:
        raise ResourceMissingError(f"{label}不存在", code=code)


def require_member(
    db: Session,
    project_id: uuid.UUID,
    user_id: uuid.UUID | None,
    *,
    label: str = "负责人",
    code: str = "owner_missing",
) -> None:
    if user_id is None:
        return
    member = db.scalar(
        select(ProjectMember.id).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
            ProjectMember.is_active.is_(True),
        )
    )
    if member is None:
        raise ResourceMissingError(f"{label}不是当前项目的有效成员", code=code)


def user_display_name(db: Session, user_id: uuid.UUID | None) -> str | None:
    if user_id is None:
        return None
    return db.scalar(select(User.display_name).where(User.id == user_id))
