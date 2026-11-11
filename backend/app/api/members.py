"""项目成员管理：授予约束在服务端强制，越级授予与调整项目管理员一律拒绝并留痕。"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    Envelope,
    MemberChanged,
    MemberData,
    PagedEnvelope,
    ok,
    ok_page,
)
from app.core.errors import InsufficientPermissionError, ResourceMissingError
from app.db.session import get_db
from app.models import ProjectMember, Role, User
from app.models.enums import RoleCode
from app.schemas import MemberGrant, MemberRoleChange
from app.services.access import ensure_can_grant
from app.services.audit import record_denial, record_permission_change

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/members",
    tags=["项目成员"],
    responses=COMMON_ERRORS,
)


def _role_row(db: Session, code: RoleCode) -> Role:
    role = db.scalar(select(Role).where(Role.code == code))
    if role is None:
        raise ResourceMissingError("角色未初始化", code="role_missing")
    return role


def _member_row(db: Session, project_id: uuid.UUID, member_id: uuid.UUID) -> ProjectMember:
    member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.id == member_id,
        )
    )
    if member is None:
        raise ResourceMissingError("成员不存在", code="member_missing")
    return member


def _role_code_of(db: Session, member: ProjectMember | None) -> str | None:
    if member is None:
        return None
    role = db.get(Role, member.role_id)
    return role.code if role else None


def _guard_admin_target(db: Session, ctx: ProjectContext, member: ProjectMember) -> None:
    """项目管理员不能调整同为项目管理员的成员（含降级），避免互相夺权。"""
    if _role_code_of(db, member) != RoleCode.PROJECT_ADMIN.value:
        return
    if ctx.is_system_admin:
        return
    record_denial(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        permission="project.member.manage",
        role=ctx.role.value,
        reason="target_is_project_admin",
    )
    raise InsufficientPermissionError("不能调整项目管理员角色")


@router.get("", response_model=PagedEnvelope[MemberData])
def list_members(
    ctx: ProjectContext = Depends(require_permission("project.member.manage")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
) -> dict:
    total = (
        db.scalar(
            select(func.count())
            .select_from(ProjectMember)
            .where(ProjectMember.project_id == ctx.project.id)
        )
        or 0
    )
    rows = db.scalars(
        select(ProjectMember)
        .where(ProjectMember.project_id == ctx.project.id)
        .order_by(ProjectMember.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page(
        [
            {
                "member_id": str(row.id),
                "user_id": str(row.user_id),
                "role_code": _role_code_of(db, row),
                "is_active": row.is_active,
            }
            for row in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", status_code=201, response_model=Envelope[MemberChanged])
def add_member(
    payload: MemberGrant,
    ctx: ProjectContext = Depends(require_permission("project.member.manage")),
    db: Session = Depends(get_db),
) -> dict:
    ensure_can_grant(db, ctx, payload.role_code)

    target_user = db.get(User, payload.user_id)
    if target_user is None or not target_user.is_active:
        raise ResourceMissingError("用户不存在或已停用", code="user_missing")
    role = _role_row(db, payload.role_code)

    member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == ctx.project.id,
            ProjectMember.user_id == payload.user_id,
        )
    )
    before = _role_code_of(db, member)
    if member is None:
        member = ProjectMember(
            project_id=ctx.project.id,
            user_id=payload.user_id,
            role_id=role.id,
            is_active=True,
            granted_by=ctx.user.id,
        )
        db.add(member)
    else:
        member.role_id = role.id
        member.is_active = True
    db.flush()

    record_permission_change(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        member_id=member.id,
        before=before,
        after=payload.role_code.value,
    )
    db.commit()
    return ok({"member_id": str(member.id), "role_code": payload.role_code.value})


@router.patch("/{member_id}", response_model=Envelope[MemberChanged])
def change_member_role(
    member_id: uuid.UUID,
    payload: MemberRoleChange,
    ctx: ProjectContext = Depends(require_permission("project.member.manage")),
    db: Session = Depends(get_db),
) -> dict:
    ensure_can_grant(db, ctx, payload.role_code)
    member = _member_row(db, ctx.project.id, member_id)
    _guard_admin_target(db, ctx, member)

    before = _role_code_of(db, member)
    member.role_id = _role_row(db, payload.role_code).id
    db.flush()
    record_permission_change(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        member_id=member.id,
        before=before,
        after=payload.role_code.value,
    )
    db.commit()
    return ok({"member_id": str(member.id), "role_code": payload.role_code.value})
