"""Browser login, current identity and password rotation."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.responses import (
    COMMON_ERRORS,
    AccessTokenData,
    CurrentUserData,
    Envelope,
    ok,
)
from app.core.config import settings
from app.core.errors import AppError, UnauthorizedError
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models import Project, ProjectMember, User
from app.models.enums import ProjectStatus
from app.schemas.auth import LoginRequest, PasswordChangeRequest
from app.services.access import role_permission_codes
from app.services.audit import record_audit

router = APIRouter(prefix="/api/v1/auth", tags=["认证"], responses=COMMON_ERRORS)


def _token_data(user: User) -> dict:
    return {
        "access_token": create_access_token(user.id, token_version=user.token_version),
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
    }


@router.post("/login", response_model=Envelope[AccessTokenData])
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(User.username == payload.username.strip()))
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise UnauthorizedError("账号或密码错误", code="invalid_credentials")

    user.last_login_at = datetime.now(timezone.utc)
    record_audit(
        db,
        project_id=None,
        actor_id=user.id,
        action="auth.login",
        target_type="user",
        target_id=user.id,
    )
    db.commit()
    return ok(_token_data(user))


@router.get("/me", response_model=Envelope[CurrentUserData])
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    memberships = db.scalars(
        select(ProjectMember)
        .join(Project, Project.id == ProjectMember.project_id)
        .where(
            ProjectMember.user_id == user.id,
            ProjectMember.is_active.is_(True),
            Project.status == ProjectStatus.ACTIVE,
        )
        .order_by(Project.code)
    ).all()
    return ok({
        "id": str(user.id),
        "username": user.username,
        "display_name": user.display_name,
        "is_system_admin": user.is_system_admin,
        "projects": [
            {
                "id": str(member.project.id),
                "code": member.project.code,
                "name": member.project.name,
                "role_code": member.role.code.value,
                "permissions": sorted(role_permission_codes(db, member.role)),
            }
            for member in memberships
        ],
    })


@router.post("/password", response_model=Envelope[AccessTokenData])
def change_password(
    payload: PasswordChangeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    locked = db.scalar(select(User).where(User.id == user.id).with_for_update())
    if locked is None or not locked.is_active:
        raise UnauthorizedError("账号不存在或已停用", code="user_inactive")
    if not verify_password(payload.current_password, locked.password_hash):
        raise AppError("原密码错误", code="current_password_invalid")
    if payload.current_password == payload.new_password:
        raise AppError("新密码不能与原密码相同", code="password_unchanged")
    locked.password_hash = hash_password(payload.new_password)
    locked.token_version += 1
    record_audit(
        db,
        project_id=None,
        actor_id=locked.id,
        action="auth.password_change",
        target_type="user",
        target_id=locked.id,
    )
    db.commit()
    return ok(_token_data(locked))
