"""HTTP 依赖：认证与门禁的薄适配层，具体判断在 `app.services.access`。

1. 项目内接口用 `require_permission(<能力码>)`，能力码见 `app/core/permissions.py`。
2. 权限只认 project_members；系统管理员标志不构成项目业务权限。
3. 系统级接口用 `require_system_permission(<能力码>)`，需同时具备 is_system_admin 与该能力。
"""

import uuid

import jwt
from fastapi import Depends, Path, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import UnauthorizedError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User
from app.services.access import (
    ProjectContext,
    ensure_capability,
    ensure_system_capability,
    resolve_project_context,
)

# OpenAPI 的 securitySchemes：声明 Authorization: Bearer <JWT>，让导出的契约里认证是必填项。
# auto_error=False 保证缺头时仍走本项目的错误信封（401 + {"error": {...}}），而不是 FastAPI 默认的 {"detail": ...}。
bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="BearerAuth",
    description="Authorization: Bearer <JWT>",
)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials.strip():
        raise UnauthorizedError("缺少 Bearer 令牌", code="unauthorized")

    token = credentials.credentials.strip()
    try:
        claims = decode_access_token(token)
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("令牌已过期", code="token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("令牌无效", code="token_invalid") from exc

    try:
        user_id = uuid.UUID(claims.get("sub", ""))
    except ValueError as exc:
        raise UnauthorizedError("令牌载荷异常", code="token_invalid") from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("账号不存在或已停用", code="user_inactive")
    return user


def get_project_context(
    project_id: uuid.UUID = Path(description="项目 ID"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectContext:
    return resolve_project_context(db, project_id, user)


def require_permission(code: str):
    """项目级能力门禁。"""

    def _dependency(
        ctx: ProjectContext = Depends(get_project_context),
        db: Session = Depends(get_db),
    ) -> ProjectContext:
        ensure_capability(db, ctx, code)
        return ctx

    return _dependency


def require_system_permission(code: str):
    """系统级能力门禁。"""

    def _dependency(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        ensure_system_capability(db, user, code)
        return user

    return _dependency


__all__ = [
    "ProjectContext",
    "get_current_user",
    "get_project_context",
    "require_permission",
    "require_system_permission",
]
