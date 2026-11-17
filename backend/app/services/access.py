"""访问控制领域服务：解析项目上下文、校验能力、约束成员授予。

分层约定：
- 这里只处理“谁能做什么”，不感知 HTTP；
- 拒绝一律先写审计再抛领域异常，保证越权尝试可追溯；
- 能力码来自 role_permissions 表，表未初始化时回退到 `app/core/permissions.py` 的矩阵。
"""

import uuid

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import (
    InsufficientPermissionError,
    ProjectAccessError,
    SystemAdminOnlyError,
)
from app.core.permissions import can_grant, permissions_for
from app.models import Permission, Project, ProjectMember, Role, RolePermission, User
from app.models.enums import ProjectStatus, RoleCode
from app.services.audit import record_denial


@dataclass(frozen=True)
class ProjectContext:
    """一次项目内请求的上下文：用户、项目、角色、能力集合。"""

    user: User
    project: Project
    role: RoleCode
    permissions: frozenset[str]
    member: ProjectMember | None = None
    is_system_admin: bool = False


def role_permission_codes(db: Session, role: Role) -> frozenset[str]:
    codes = frozenset(
        db.scalars(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role.id)
        ).all()
    )
    return codes or permissions_for(RoleCode(role.code))


def system_permission_codes(db: Session) -> frozenset[str]:
    role = db.scalar(select(Role).where(Role.code == RoleCode.SYS_ADMIN))
    if role is None:
        return permissions_for(RoleCode.SYS_ADMIN)
    return role_permission_codes(db, role)


def _deny(
    db: Session,
    *,
    project_id: uuid.UUID | None,
    actor: User | None,
    reason: str,
    permission: str | None = None,
    role: str | None = None,
    detail: dict | None = None,
) -> None:
    record_denial(
        db,
        project_id=project_id,
        actor_id=actor.id if actor else None,
        permission=permission,
        role=role,
        reason=reason,
        detail=detail,
    )


def resolve_project_context(db: Session, project_id: uuid.UUID, user: User) -> ProjectContext:
    """按 project_id + user 解析项目上下文。

    只认 project_members 授权：系统管理员标志不构成项目业务权限，
    要读写项目数据必须先被加入该项目（否则 403 project_forbidden）。
    """
    project = db.get(Project, project_id)
    if project is None:
        _deny(db, project_id=None, actor=user, reason="project_not_found")
        raise ProjectAccessError("project not found or not accessible")

    if project.status != ProjectStatus.ACTIVE:
        _deny(db, project_id=project.id, actor=user, reason="project_not_active")
        raise ProjectAccessError("project is not active")

    member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user.id,
            ProjectMember.is_active.is_(True),
        )
    )
    if member is None:
        _deny(
            db,
            project_id=project.id,
            actor=user,
            reason="no_membership",
            detail={"is_system_admin": user.is_system_admin},
        )
        raise ProjectAccessError("project not found or not accessible")

    role = db.get(Role, member.role_id)
    if role is None:
        _deny(db, project_id=project.id, actor=user, reason="role_missing")
        raise ProjectAccessError("project not found or not accessible")

    # sys_admin 只是能力映射用的字典行，不能作为项目成员角色：
    # 系统权限一律只认 users.is_system_admin，避免出现两套判定。
    if role.code == RoleCode.SYS_ADMIN:
        _deny(
            db,
            project_id=project.id,
            actor=user,
            reason="sys_admin_role_not_assignable",
            role=role.code,
        )
        raise ProjectAccessError("project not found or not accessible")

    return ProjectContext(
        user=user,
        project=project,
        role=RoleCode(role.code),
        permissions=role_permission_codes(db, role),
        member=member,
        is_system_admin=user.is_system_admin,
    )


def ensure_capability(db: Session, ctx: ProjectContext, code: str) -> None:
    """缺能力即拒绝，并记录缺少的能力码与当前角色。"""
    if code in ctx.permissions:
        return
    _deny(
        db,
        project_id=ctx.project.id,
        actor=ctx.user,
        reason="missing_capability",
        permission=code,
        role=ctx.role.value,
    )
    raise InsufficientPermissionError(f"缺少能力：{code}")


def ensure_any_capability(db: Session, ctx: ProjectContext, codes: tuple[str, ...]) -> None:
    """任一能力满足即通过；用于内部排障这类多角色共用的窄接口。"""
    if any(code in ctx.permissions for code in codes):
        return
    permission = "|".join(codes)
    _deny(
        db,
        project_id=ctx.project.id,
        actor=ctx.user,
        reason="missing_capability",
        permission=permission,
        role=ctx.role.value,
    )
    raise InsufficientPermissionError(f"缺少任一能力：{' 或 '.join(codes)}")


def ensure_system_capability(db: Session, user: User, code: str) -> None:
    """系统级能力：必须同时是系统管理员且持有该能力。"""
    allowed = system_permission_codes(db) if user.is_system_admin else frozenset()
    if code in allowed:
        return
    _deny(
        db,
        project_id=None,
        actor=user,
        reason="missing_system_capability",
        permission=code,
        role=RoleCode.SYS_ADMIN.value if user.is_system_admin else "none",
    )
    raise SystemAdminOnlyError(f"缺少系统能力：{code}")


def ensure_engine_verification_capability(db: Session, user: User) -> None:
    """入口人工核验：系统管理员保留 engine.manage；项目角色可用窄权限 engine.verify。

    引擎目录是全局资源，但核验动作允许任一项目内持有 engine.verify 的运营/项目管理员执行；
    不要求系统管理员身份，也不授予目录增改。
    """
    if user.is_system_admin and "engine.manage" in system_permission_codes(db):
        return
    memberships = db.execute(
        select(ProjectMember, Role)
        .join(Role, Role.id == ProjectMember.role_id)
        .where(ProjectMember.user_id == user.id, ProjectMember.is_active.is_(True))
    ).all()
    for member, role in memberships:
        if role.code == RoleCode.SYS_ADMIN:
            continue
        if member.is_active and "engine.verify" in role_permission_codes(db, role):
            return
    _deny(
        db,
        project_id=None,
        actor=user,
        reason="missing_capability",
        permission="engine.verify",
        role="none",
    )
    raise InsufficientPermissionError("缺少能力：engine.verify")


def ensure_can_grant(db: Session, ctx: ProjectContext, target: RoleCode) -> None:
    """成员授予约束：只能授予业务角色，不得转授项目管理员/系统管理员或管理类能力。"""
    if can_grant(ctx.role, target):
        return
    _deny(
        db,
        project_id=ctx.project.id,
        actor=ctx.user,
        reason="grant_denied",
        permission="project.member.manage",
        role=ctx.role.value,
        detail={"target_role": target.value},
    )
    raise InsufficientPermissionError(f"不能授予角色：{target.value}")
