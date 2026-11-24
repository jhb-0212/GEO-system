"""系统账号目录的读取与查重，从 `api/system_admin.py` 下沉。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ResourceMissingError
from app.models import User


def account_payload(user: User) -> dict:
    return {
        "id": str(user.id),
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "is_active": user.is_active,
        "is_system_admin": user.is_system_admin,
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
    }


def page_users(
    db: Session, *, q: str, page: int, page_size: int
) -> tuple[int, list[User]]:
    stmt = select(User)
    term = q.strip()
    if term:
        pattern = f"%{term}%"
        stmt = stmt.where(
            or_(
                User.username.ilike(pattern),
                User.display_name.ilike(pattern),
                User.email.ilike(pattern),
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    users = db.scalars(
        stmt.order_by(User.username).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return int(total), list(users)


def username_exists(db: Session, username: str) -> bool:
    return db.scalar(select(User.id).where(User.username == username)) is not None


def email_exists(db: Session, email: str, *, exclude_id: uuid.UUID | None = None) -> bool:
    stmt = select(User.id).where(User.email == email)
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    return db.scalar(stmt) is not None


def user_for_update(db: Session, user_id: uuid.UUID) -> User:
    target = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if target is None:
        raise ResourceMissingError("用户不存在", code="user_not_found")
    return target
