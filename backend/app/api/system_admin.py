"""系统管理员专用动作：重置他人密码、解除某账号/IP 的登录失败限流。

两者都是账号安全动作，不挂项目能力码——只允许 `is_system_admin`，
避免项目管理员通过重置密码接管他人账号。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api import auth as auth_api
from app.api.deps import get_current_user
from app.api.responses import (
    COMMON_ERRORS,
    DataProvenanceData,
    Envelope,
    PagedEnvelope,
    UserAccountData,
    ok,
    ok_page,
)
from app.core.errors import AppError, ResourceMissingError, SystemAdminOnlyError
from app.core.security import hash_password
from app.db.session import get_db
from app.models import User
from app.schemas.auth import LoginThrottleResetRequest, PasswordResetRequest, UserCreateRequest, UserUpdateRequest
from app.services.audit import record_audit
from app.services.data_provenance import collect_data_provenance
from app.services.user_accounts import (
    account_payload as _account_data,
    email_exists,
    page_users,
    user_for_update,
    username_exists,
)

router = APIRouter(prefix="/api/v1/system", tags=["系统管理"], responses=COMMON_ERRORS)


def _require_system_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_system_admin:
        raise SystemAdminOnlyError("仅系统管理员可执行该操作")
    return user


@router.get("/users", response_model=PagedEnvelope[UserAccountData])
def list_users(
    admin: User = Depends(_require_system_admin),
    db: Session = Depends(get_db),
    q: str = Query("", max_length=64, description="按用户名/邮箱/显示名模糊搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    """系统账号目录：只给系统管理员，用于建号后加入项目前确认账号状态。"""
    total, users = page_users(db, q=q, page=page, page_size=page_size)
    return ok_page(
        [_account_data(user) for user in users],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/users", status_code=201, response_model=Envelope[UserAccountData])
def create_user(
    payload: UserCreateRequest,
    admin: User = Depends(_require_system_admin),
    db: Session = Depends(get_db),
) -> dict:
    """建号：只创建账号，不授予系统管理员；项目权限仍由成员接口授予。"""
    if username_exists(db, payload.username):
        raise AppError("用户名已存在", code="username_exists")
    if payload.email and email_exists(db, payload.email):
        raise AppError("邮箱已存在", code="email_exists")
    user = User(
        username=payload.username,
        display_name=payload.display_name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        is_active=True,
        is_system_admin=False,
    )
    db.add(user)
    db.flush()
    record_audit(
        db,
        project_id=None,
        actor_id=admin.id,
        action="auth.user_create",
        target_type="user",
        target_id=user.id,
        payload={"username": user.username, "operator": admin.username},
    )
    db.commit()
    return ok(_account_data(user))


@router.patch("/users/{user_id}", response_model=Envelope[UserAccountData])
def update_user(
    user_id: uuid.UUID,
    payload: UserUpdateRequest,
    admin: User = Depends(_require_system_admin),
    db: Session = Depends(get_db),
) -> dict:
    """改资料或启用/停用账号；停用会 `token_version += 1`，旧会话立即失效。"""
    target = user_for_update(db, user_id)

    changes: dict = {}
    if payload.display_name is not None and payload.display_name != target.display_name:
        changes["display_name"] = {"before": target.display_name, "after": payload.display_name}
        target.display_name = payload.display_name
    if payload.email is not None and payload.email != target.email:
        if email_exists(db, payload.email, exclude_id=target.id):
            raise AppError("邮箱已存在", code="email_exists")
        changes["email"] = {"before": target.email, "after": payload.email}
        target.email = payload.email
    if payload.is_active is not None and payload.is_active != target.is_active:
        if not payload.is_active:
            if target.id == admin.id:
                raise AppError("不能停用自己的账号", code="cannot_deactivate_self")
            if target.is_system_admin:
                raise AppError(
                    "不能停用其他系统管理员，请走独立运维流程",
                    code="cannot_deactivate_system_admin",
                )
            target.token_version += 1
        changes["is_active"] = {"before": target.is_active, "after": payload.is_active}
        target.is_active = payload.is_active

    if not changes:
        return ok(_account_data(target))
    db.flush()
    record_audit(
        db,
        project_id=None,
        actor_id=admin.id,
        action="auth.user_update",
        target_type="user",
        target_id=target.id,
        payload={"username": target.username, "changes": changes, "operator": admin.username},
    )
    db.commit()
    return ok(_account_data(target))


@router.get(
    "/data-provenance",
    response_model=Envelope[DataProvenanceData],
)
def get_data_provenance(
    admin: User = Depends(_require_system_admin),
    db: Session = Depends(get_db),
) -> dict:
    """P16 只读清点：原型/模拟项目、演示账号、历史本地导入批次与残留行数。"""
    return ok(collect_data_provenance(db))


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
    target = user_for_update(db, user_id)
    if not target.is_active:
        raise AppError("账号已停用，无法重置密码", code="user_inactive")
    if target.is_system_admin and target.id != admin.id:
        # 任一管理员都能改另一个管理员的密码并让旧会话失效，等于单人接管全部管理权限。
        raise AppError(
            "不能重置其他系统管理员的密码，请走独立的运维口令流程",
            code="cannot_reset_system_admin",
        )

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
        cleared_keys = auth_api.login_throttle.reset(payload.username, client_ip)
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
