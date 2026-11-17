"""Browser login, current identity and password rotation."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
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
from app.core.errors import AppError, TooManyRequestsError, UnauthorizedError
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models import Project, ProjectMember, User
from app.models.enums import ProjectStatus
from app.schemas.auth import LoginRequest, PasswordChangeRequest
from app.services.access import role_permission_codes
from app.services.audit import record_audit
from app.services.login_guard import LoginThrottle

router = APIRouter(prefix="/api/v1/auth", tags=["认证"], responses=COMMON_ERRORS)

# 模块级实例便于测试注入 FakeRedis；生产按需惰性建立连接。
login_throttle = LoginThrottle()


def _client_ip(request: Request) -> str:
    """取真实来源 IP：只有配置了可信代理层数才解析转发头。

    `trusted_proxy_count=0` 时完全忽略 X-Forwarded-For / X-Real-IP，避免客户端
    直接伪造头绕过登录限流。Nginx 前置时设为 1，取 XFF 右侧第 1 个地址（即
    Nginx 实际看到的客户端地址），不是最左侧可伪造段。
    """
    trusted = max(0, int(settings.trusted_proxy_count))
    if trusted > 0:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            parts = [part.strip() for part in forwarded.split(",") if part.strip()]
            if len(parts) >= trusted:
                return parts[-trusted]
    return request.client.host if request.client else "unknown"


def _token_data(user: User) -> dict:
    return {
        "access_token": create_access_token(user.id, token_version=user.token_version),
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
    }


@router.post("/login", response_model=Envelope[AccessTokenData])
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    username = payload.username.strip()
    client_ip = _client_ip(request)

    wait_seconds = login_throttle.check(username, client_ip)
    if wait_seconds > 0:
        raise TooManyRequestsError(
            f"登录尝试过于频繁，请 {wait_seconds} 秒后再试", code="login_rate_limited"
        )

    user = db.scalar(select(User).where(User.username == username))
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        locked = login_throttle.register_failure(username, client_ip)
        if locked:
            # 只有刚触达阈值时写一条审计，避免每次失败都落库放大写入
            record_audit(
                db,
                project_id=None,
                actor_id=None,
                action="auth.login_locked",
                target_type="user",
                payload={"username": username, "client_ip": client_ip},
            )
            db.commit()
        raise UnauthorizedError("账号或密码错误", code="invalid_credentials")

    login_throttle.reset(username, client_ip)
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
