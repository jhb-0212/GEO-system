"""项目成员管理：授予约束在服务端强制，越级授予与调整项目管理员一律拒绝并留痕。"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    Envelope,
    MemberChanged,
    MemberData,
    PagedEnvelope,
    UserCandidateData,
    ok,
    ok_page,
)
from app.core.errors import AppError, InsufficientPermissionError, ResourceMissingError
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
    rows = db.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == ctx.project.id)
        .order_by(ProjectMember.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page(
        [
            {
                "member_id": str(member.id),
                "user_id": str(member.user_id),
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email,
                "role_code": _role_code_of(db, member),
                "is_active": member.is_active,
            }
            for member, user in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/candidates", response_model=Envelope[list[UserCandidateData]])
def list_member_candidates(
    ctx: ProjectContext = Depends(require_permission("project.member.manage")),
    db: Session = Depends(get_db),
    q: str = Query("", max_length=64, description="按用户名/邮箱/显示名模糊搜索"),
) -> dict:
    """可授予的候选用户：排除当前项目在职成员（已停用成员可重新授予），默认按用户名排序。"""
    existing_user_ids = select(ProjectMember.user_id).where(
        ProjectMember.project_id == ctx.project.id,
        ProjectMember.is_active.is_(True),
    )
    stmt = (
        select(User)
        .where(User.is_active.is_(True))
        .where(User.id.not_in(existing_user_ids))
    )
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
    users = db.scalars(stmt.order_by(User.username).limit(20)).all()
    return ok(
        [
            {
                "id": str(user.id),
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email,
            }
            for user in users
        ]
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
        from app.services.organization_settings import enforce_project_member_quota

        enforce_project_member_quota(db, ctx.project)
        member = ProjectMember(
            project_id=ctx.project.id,
            user_id=payload.user_id,
            role_id=role.id,
            is_active=True,
            granted_by=ctx.user.id,
        )
        db.add(member)
    else:
        # 已存在成员必须与 PATCH/DELETE 走同一守卫：新增接口不能成为降级项目管理员的旁路。
        _guard_admin_target(db, ctx, member)
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


@router.delete("/{member_id}", response_model=Envelope[MemberChanged])
def deactivate_member(
    member_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("project.member.manage")),
    db: Session = Depends(get_db),
) -> dict:
    """停用成员：保留记录并把 is_active 置 false，权限立即失效，操作留痕。"""
    member = _member_row(db, ctx.project.id, member_id)
    if member.user_id == ctx.user.id:
        raise AppError("不能停用自己", code="cannot_remove_self")
    _guard_admin_target(db, ctx, member)

    before = _role_code_of(db, member)
    member.is_active = False
    db.flush()
    record_permission_change(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        member_id=member.id,
        before=before,
        after="deactivated",
    )
    db.commit()
    return ok({"member_id": str(member.id), "role_code": before})
