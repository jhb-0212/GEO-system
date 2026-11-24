"""项目成员管理：授予约束在服务端强制，越级授予与调整项目管理员一律拒绝并留痕。"""

import uuid

from fastapi import APIRouter, Depends, Query
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
from app.models import ProjectMember, User
from app.models.enums import RoleCode
from app.schemas import MemberGrant, MemberRoleChange
from app.services.access import ensure_can_grant
from app.services.audit import record_denial, record_permission_change
from app.services.member_registry import (
    member_by_user,
    member_candidates,
    member_row as _member_row,
    page_members,
    role_code_of,
    role_row as _role_row,
)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/members",
    tags=["项目成员"],
    responses=COMMON_ERRORS,
)


def _guard_admin_target(db: Session, ctx: ProjectContext, member: ProjectMember) -> None:
    """项目管理员不能调整同为项目管理员的成员（含降级），避免互相夺权。"""
    if role_code_of(db, member) != RoleCode.PROJECT_ADMIN.value:
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
    total, rows = page_members(
        db, ctx.project.id, page=page, page_size=page_size
    )
    return ok_page(
        [
            {
                "member_id": str(member.id),
                "user_id": str(member.user_id),
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email,
                "role_code": role_code,
                "is_active": member.is_active,
            }
            for member, user, role_code in rows
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
    users = member_candidates(db, ctx.project.id, q)
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

    member = member_by_user(db, ctx.project.id, payload.user_id)
    before = role_code_of(db, member)
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
        if not member.is_active:
            # 恢复停用成员同样会增加在职人数，必须过同一配额闸门。
            from app.services.organization_settings import enforce_project_member_quota

            enforce_project_member_quota(db, ctx.project)
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

    before = role_code_of(db, member)
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

    before = role_code_of(db, member)
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
