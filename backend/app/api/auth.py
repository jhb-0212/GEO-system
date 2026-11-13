"""认证接口：登录换 JWT、当前用户。

- `POST /login` 公开；`GET /me` 需 Bearer 令牌。
- 本期不做改密与令牌硬失效；旧令牌按 `token_invalid` / `token_expired` / `user_inactive` 处理。
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.responses import (
    COMMON_ERRORS,
    Envelope,
    LoginData,
    MeData,
    MeProjectItem,
    UserProfileData,
    ok,
)
from app.core.errors import UnauthorizedError
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.models import Project, ProjectMember, Role, User
from app.schemas import LoginRequest

router = APIRouter(prefix="/api/v1/auth", tags=["认证"], responses=COMMON_ERRORS)


def _profile(user: User) -> UserProfileData:
    return UserProfileData(
        id=str(user.id),
        username=user.username,
        display_name=user.display_name,
        is_system_admin=user.is_system_admin,
    )


def _accessible_projects(db: Session, user: User) -> list[MeProjectItem]:
    """只返回当前用户仍是活跃成员的项目；系统管理员不自动拿全量项目。"""
    rows = db.execute(
        select(Project, Role)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .join(Role, Role.id == ProjectMember.role_id)
        .where(
            ProjectMember.user_id == user.id,
            ProjectMember.is_active.is_(True),
        )
        .order_by(Project.code)
    ).all()
    return [
        MeProjectItem(
            id=str(p.id),
            code=p.code,
            name=p.name,
            status=p.status,
            role_code=role.code,
        )
        for p, role in rows
    ]


@router.post("/login", response_model=Envelope[LoginData])
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not user.is_active or not verify_password(
        payload.password, user.password_hash
    ):
        # 用户名不存在与密码错误统一返回同一错误，不暴露账号是否存在；失败不回写登录时间。
        raise UnauthorizedError("账号或密码不正确", code="unauthorized")

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    token = create_access_token(user.id)
    return ok({"access_token": token, "token_type": "bearer", "user": _profile(user)})


@router.get("/me", response_model=Envelope[MeData])
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return ok(
        MeData(
            id=str(user.id),
            username=user.username,
            display_name=user.display_name,
            is_system_admin=user.is_system_admin,
            projects=_accessible_projects(db, user),
        )
    )
