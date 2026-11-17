"""系统管理员专用动作：重置他人密码、解除某账号/IP 的登录失败限流。

两者都是账号安全动作，不挂项目能力码——只允许 `is_system_admin`，
避免项目管理员通过重置密码接管他人账号。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import auth as auth_api
from app.api.deps import get_current_user
from app.api.responses import COMMON_ERRORS, Envelope, ok
from app.core.errors import AppError, ResourceMissingError, SystemAdminOnlyError
from app.core.security import hash_password
from app.db.session import get_db
from app.models import User
from app.schemas.auth import LoginThrottleResetRequest, PasswordResetRequest
from app.services.audit import record_audit

router = APIRouter(prefix="/api/v1/system", tags=["系统管理"], responses=COMMON_ERRORS)


def _require_system_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_system_admin:
        raise SystemAdminOnlyError("仅系统管理员可执行该操作")
    return user


@router.post(
    "/users/{user_id}/reset-password",
    response_model=Envelope[dict],
)
def reset_user_password(
    user_id: uuid.UUID,
    payload: PasswordResetRequest,
    admin: User = Depends(_require_system_admin),
    db: Session = Depends(get_db),
) -> dict:
    """管理员给指定账号设新密码：不改 `is_active`，但 `token_version += 1` 让旧会话全部失效。"""
    target = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if target is None:
        raise ResourceMissingError("用户不存在", code="user_not_found")
    if not target.is_active:
        raise AppError("账号已停用，无法重置密码", code="user_inactive")

    target.password_hash = hash_password(payload.new_password)
    target.token_version += 1
    record_audit(
        db,
        project_id=None,
        actor_id=admin.id,
        action="auth.password_reset",
        target_type="user",
        target_id=target.id,
        payload={"username": target.username, "operator": admin.username},
    )
    db.commit()
    return ok({"ok": True, "username": target.username})


@router.post(
    "/login-throttle/reset",
    response_model=Envelope[dict],
)
def reset_login_throttle(
    payload: LoginThrottleResetRequest,
    admin: User = Depends(_require_system_admin),
    db: Session = Depends(get_db),
) -> dict:
    """清掉该账号 + IP 当前窗口的失败计数，让被限流的登录立刻恢复。

    限流键按「分钟桶 / 小时桶」分片，`reset` 只清当前窗口；历史窗口会自然过期。
    """
    client_ip = (payload.client_ip or "").strip()
    if client_ip:
        # 走模块属性而不是导入时绑定，测试才能 monkeypatch auth.login_throttle 注入 FakeRedis
        auth_api.login_throttle.reset(payload.username, client_ip)
        cleared_keys = 4
    else:
        # 管理员通常不知道用户 IP：只凭账号名清该账号的窗口桶与最近失败 IP 的窗口桶
        cleared_keys = auth_api.login_throttle.reset_username(payload.username)
    record_audit(
        db,
        project_id=None,
        actor_id=admin.id,
        action="auth.throttle_reset",
        target_type="user",
        payload={
            "username": payload.username,
            "client_ip": client_ip or None,
            "cleared_keys": cleared_keys,
            "operator": admin.username,
        },
    )
    db.commit()
    return ok({"ok": True, "username": payload.username, "client_ip": client_ip or None, "cleared_keys": cleared_keys})
