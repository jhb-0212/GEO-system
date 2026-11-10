"""请求级依赖：认证、项目上下文、角色校验。

约定：项目内接口一律 `Depends(get_project_context)` 或 `require_project_role(...)`，
服务端依据 project_members 判断授权，前端传来的 project_id 只当定位参数。
"""

import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, Path
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import (
    InsufficientRoleError,
    ProjectAccessError,
    SystemAdminOnlyError,
    UnauthorizedError,
)
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import Project, ProjectMember, Role, User
from app.models.enums import ProjectStatus, RoleCode


@dataclass(frozen=True)
class ProjectContext:
    """一次项目内请求的上下文：用户、项目、其在该项目的角色。"""

    user: User
    project: Project
    role: RoleCode | None
    is_system_admin: bool = False


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise UnauthorizedError("缺少 Bearer 令牌", code="unauthorized")

    token = authorization.split(" ", 1)[1].strip()
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


def get_system_admin(user: User = Depends(get_current_user)) -> User:
    """系统管理员专用：建项目、维护引擎目录、跨项目管理成员。"""
    if not user.is_system_admin:
        raise SystemAdminOnlyError("仅系统管理员可操作")
    return user


def get_project_context(
    project_id: uuid.UUID = Path(description="项目 ID"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectContext:
    """项目上下文：先确认项目可用，再确认成员授权；系统管理员可跨项目。"""
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectAccessError("project not found or not accessible")
    if project.status != ProjectStatus.ACTIVE:
        raise ProjectAccessError("project is not active")

    if user.is_system_admin:
        return ProjectContext(user=user, project=project, role=RoleCode.ADMIN, is_system_admin=True)

    member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user.id,
            ProjectMember.is_active.is_(True),
        )
    )
    if member is None:
        raise ProjectAccessError("project not found or not accessible")

    role = db.get(Role, member.role_id)
    role_code = RoleCode(role.code) if role is not None else None
    return ProjectContext(user=user, project=project, role=role_code)


def require_project_role(*allowed: RoleCode):
    """角色门禁：系统管理员始终通过，项目成员按角色判断。"""

    allowed_set = {RoleCode(code) for code in allowed}

    def _dependency(ctx: ProjectContext = Depends(get_project_context)) -> ProjectContext:
        if ctx.is_system_admin:
            return ctx
        if ctx.role is None or ctx.role not in allowed_set:
            raise InsufficientRoleError("insufficient role for this operation")
        return ctx

    return _dependency
