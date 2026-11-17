"""系统管理员动作：重置他人密码、凭账号解封登录限流。"""

import uuid

import pytest
import redis

from app.core.config import settings
from app.core.security import create_access_token


def _headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


class _FakeRedis:
    """只实现登录限流用到的命令。"""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.sets: dict[str, set[str]] = {}

    def get(self, key):
        return self.counts.get(key)

    def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key, seconds):
        return True

    def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)
        return 1

    def smembers(self, key):
        return self.sets.get(key, set())

    def delete(self, *keys):
        for key in keys:
            self.counts.pop(key, None)
            self.sets.pop(key, None)
        return len(keys)


def _install_throttle(monkeypatch, fake: _FakeRedis) -> None:
    from app.api import auth as auth_api
    from app.services.login_guard import LoginThrottle

    monkeypatch.setattr(auth_api, "login_throttle", LoginThrottle(client=fake))


# ---------- 重置密码 ----------


def test_reset_password_by_system_admin(client, db, user_factory):
    admin = user_factory(f"sysadmin-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    target = user_factory(f"target-{uuid.uuid4().hex[:6]}")
    old_token = create_access_token(target.id, token_version=target.token_version)

    response = client.post(
        f"/api/v1/system/users/{target.id}/reset-password",
        json={"new_password": "reset-test-password"},
        headers=_headers(admin),
    )
    assert response.status_code == 200
    assert response.json()["data"]["username"] == target.username
    assert target.token_version == 1

    # 旧令牌与旧密码同时失效，新密码可登录
    stale = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_token}"})
    assert stale.json()["error"]["code"] == "token_stale"
    assert client.post(
        "/api/v1/auth/login", json={"username": target.username, "password": "unit-test-password"}
    ).status_code == 401
    assert client.post(
        "/api/v1/auth/login", json={"username": target.username, "password": "reset-test-password"}
    ).status_code == 200

    from sqlalchemy import select

    from app.models import AuditLog

    audit = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "auth.password_reset",
            AuditLog.target_id == target.id,
        )
    )
    assert audit is not None
    assert audit.payload["operator"] == admin.username
    assert audit.payload["username"] == target.username


def test_reset_password_requires_system_admin(client, user_factory):
    normal = user_factory(f"normal-{uuid.uuid4().hex[:6]}")
    target = user_factory(f"target-{uuid.uuid4().hex[:6]}")

    response = client.post(
        f"/api/v1/system/users/{target.id}/reset-password",
        json={"new_password": "reset-test-password"},
        headers=_headers(normal),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "system_admin_only"
    assert target.token_version == 0


def test_reset_password_unknown_user(client, user_factory):
    admin = user_factory(f"sysadmin-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    response = client.post(
        f"/api/v1/system/users/{uuid.uuid4()}/reset-password",
        json={"new_password": "reset-test-password"},
        headers=_headers(admin),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "user_not_found"


def test_reset_password_inactive_user(client, db, user_factory):
    admin = user_factory(f"sysadmin-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    target = user_factory(f"inactive-{uuid.uuid4().hex[:6]}")
    target.is_active = False
    db.flush()

    response = client.post(
        f"/api/v1/system/users/{target.id}/reset-password",
        json={"new_password": "reset-test-password"},
        headers=_headers(admin),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "user_inactive"


# ---------- 解除登录限流 ----------


def test_throttle_reset_by_username_unblocks_login(client, user_factory, monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(settings, "login_rate_limit_per_minute", 2)
    monkeypatch.setattr(settings, "login_rate_limit_per_hour", 100)
    _install_throttle(monkeypatch, fake)

    user = user_factory(f"throttle-{uuid.uuid4().hex[:6]}")
    admin = user_factory(f"sysadmin-{uuid.uuid4().hex[:6]}", is_system_admin=True)

    for _ in range(2):
        assert client.post(
            "/api/v1/auth/login", json={"username": user.username, "password": "wrong"}
        ).status_code == 401
    blocked = client.post("/api/v1/auth/login", json={"username": user.username, "password": "wrong"})
    assert blocked.status_code == 429
    # 连正确密码也被挡
    assert client.post(
        "/api/v1/auth/login", json={"username": user.username, "password": "unit-test-password"}
    ).status_code == 429

    # 只给账号名（不给 IP）也要能解封
    response = client.post(
        "/api/v1/system/login-throttle/reset",
        json={"username": user.username},
        headers=_headers(admin),
    )
    assert response.status_code == 200
    assert response.json()["data"]["cleared_keys"] >= 2
    assert client.post(
        "/api/v1/auth/login", json={"username": user.username, "password": "unit-test-password"}
    ).status_code == 200


def test_throttle_reset_requires_system_admin(client, user_factory):
    normal = user_factory(f"normal-{uuid.uuid4().hex[:6]}")
    response = client.post(
        "/api/v1/system/login-throttle/reset",
        json={"username": "someone"},
        headers=_headers(normal),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "system_admin_only"


def test_throttle_reset_survives_redis_down(client, user_factory, monkeypatch):
    """Redis 不可用时解除动作不报错（限流本身也是 fail-open）。"""

    class _Broken:
        def get(self, key):
            raise redis.RedisError("down")

        def incr(self, key):
            raise redis.RedisError("down")

        def expire(self, key, seconds):
            raise redis.RedisError("down")

        def sadd(self, key, value):
            raise redis.RedisError("down")

        def smembers(self, key):
            raise redis.RedisError("down")

        def delete(self, *keys):
            raise redis.RedisError("down")

    from app.api import auth as auth_api
    from app.services.login_guard import LoginThrottle

    monkeypatch.setattr(auth_api, "login_throttle", LoginThrottle(client=_Broken()))
    admin = user_factory(f"sysadmin-{uuid.uuid4().hex[:6]}", is_system_admin=True)

    response = client.post(
        "/api/v1/system/login-throttle/reset",
        json={"username": "someone"},
        headers=_headers(admin),
    )
    assert response.status_code == 200
    assert response.json()["data"]["cleared_keys"] == 0


def test_reset_password_rejects_other_system_admin(client, db, user_factory):
    """任一管理员不能改另一个管理员的密码，否则单人即可接管全部管理权限。"""
    admin = user_factory(f"sysadmin-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    other = user_factory(f"sysadmin-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    response = client.post(
        f"/api/v1/system/users/{other.id}/reset-password",
        json={"new_password": "another-strong-password"},
        headers=_headers(admin),
    )
    assert response.status_code in (400, 403)
    assert response.json()["error"]["code"] == "cannot_reset_system_admin"
