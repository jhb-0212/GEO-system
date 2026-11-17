"""Real login and token invalidation through the public HTTP API."""

import uuid

import jwt
import pytest
import redis

from app.core.config import settings
from app.core.security import create_access_token
from app.models.enums import RoleCode


def test_login_me_and_bad_credentials(client, db, project_factory, user_factory, member_factory):
    project = project_factory("auth-project")
    user = user_factory("auth-editor")
    member_factory(project, user, RoleCode.EDITOR)

    bad = client.post("/api/v1/auth/login", json={"username": user.username, "password": "wrong"})
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "invalid_credentials"
    assert user.last_login_at is None

    response = client.post(
        "/api/v1/auth/login",
        json={"username": user.username, "password": "unit-test-password"},
    )
    assert response.status_code == 200
    assert user.last_login_at is not None
    token = response.json()["data"]["access_token"]
    assert jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])["tv"] == 0

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["data"]["username"] == user.username
    assert me.json()["data"]["projects"][0]["id"] == str(project.id)
    assert "monitoring.execute" in me.json()["data"]["projects"][0]["permissions"]
    assert "password_hash" not in me.text


@pytest.mark.parametrize(
    ("role", "resource", "permission"),
    [
        (RoleCode.PROJECT_ADMIN, "members", "project.member.manage"),
        (RoleCode.EDITOR, "monitoring/rounds", "monitoring.read"),
        (RoleCode.REVIEWER, "audit-logs", "audit.read"),
        (RoleCode.VIEWER, "channels", "channel.read"),
        (RoleCode.LEAD_OPS, "leads", "lead.read"),
    ],
)
def test_each_project_role_uses_real_login(
    client, project_factory, user_factory, member_factory, role, resource, permission
):
    suffix = uuid.uuid4().hex[:8]
    project = project_factory(f"auth-{suffix}")
    user = user_factory(f"{role.value}-{suffix}")
    member_factory(project, user, role)

    login = client.post(
        "/api/v1/auth/login",
        json={"username": user.username, "password": "unit-test-password"},
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    projects = me.json()["data"]["projects"]
    assert len(projects) == 1
    assert projects[0]["id"] == str(project.id)
    assert projects[0]["role_code"] == role.value
    assert permission in projects[0]["permissions"]
    assert client.get(f"/api/v1/projects/{project.id}/{resource}", headers=headers).status_code == 200


def test_password_change_invalidates_old_token(client, user_factory):
    user = user_factory("auth-password")
    old_token = create_access_token(user.id, token_version=user.token_version)
    headers = {"Authorization": f"Bearer {old_token}"}

    changed = client.post(
        "/api/v1/auth/password",
        json={"current_password": "unit-test-password", "new_password": "new-test-password"},
        headers=headers,
    )
    assert changed.status_code == 200
    new_token = changed.json()["data"]["access_token"]
    assert user.token_version == 1
    assert client.get("/api/v1/auth/me", headers=headers).json()["error"]["code"] == "token_stale"
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"username": user.username, "password": "unit-test-password"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": user.username, "password": "new-test-password"}).status_code == 200


def test_inactive_and_legacy_token_rejected(client, db, user_factory):
    user = user_factory("auth-inactive")
    legacy = jwt.encode(
        {"sub": str(user.id), "type": "access"}, settings.secret_key, algorithm=settings.jwt_algorithm
    )
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {legacy}"}).json()["error"]["code"] == "token_stale"

    token = create_access_token(user.id, token_version=user.token_version)
    user.is_active = False
    db.flush()
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "user_inactive"


# ---------- 登录失败限流 ----------


class _FakeRedis:
    """只实现登录限流用到的四个命令，避免测试依赖真实 Redis。"""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.expires: dict[str, int] = {}

    def get(self, key):
        return self.counts.get(key)

    def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key, seconds):
        self.expires[key] = seconds
        return True

    def delete(self, *keys):
        for key in keys:
            self.counts.pop(key, None)
        return len(keys)


class _BrokenRedis:
    """所有命令都抛 RedisError，模拟 Redis 宕机。"""

    def get(self, key):
        raise redis.RedisError("redis down")

    def incr(self, key):
        raise redis.RedisError("redis down")

    def expire(self, key, seconds):
        raise redis.RedisError("redis down")

    def delete(self, *keys):
        raise redis.RedisError("redis down")


def _install_throttle(monkeypatch, client):
    from app.api import auth as auth_api
    from app.services.login_guard import LoginThrottle

    monkeypatch.setattr(auth_api, "login_throttle", LoginThrottle(client=client))


def test_login_rate_limited_after_repeated_failures(
    client, db, user_factory, monkeypatch
):
    from sqlalchemy import select

    from app.models import AuditLog

    user = user_factory(f"auth-throttle-{uuid.uuid4().hex[:6]}")
    monkeypatch.setattr(settings, "login_rate_limit_per_minute", 2)
    monkeypatch.setattr(settings, "login_rate_limit_per_hour", 100)
    _install_throttle(monkeypatch, _FakeRedis())

    for _ in range(2):
        failed = client.post(
            "/api/v1/auth/login",
            json={"username": user.username, "password": "wrong"},
        )
        assert failed.status_code == 401

    blocked = client.post(
        "/api/v1/auth/login",
        json={"username": user.username, "password": "wrong"},
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "login_rate_limited"

    locked_audit = db.scalar(select(AuditLog).where(AuditLog.action == "auth.login_locked"))
    assert locked_audit is not None
    assert locked_audit.payload["username"] == user.username


def test_login_success_resets_failure_counter(client, user_factory, monkeypatch):
    user = user_factory(f"auth-reset-{uuid.uuid4().hex[:6]}")
    monkeypatch.setattr(settings, "login_rate_limit_per_minute", 2)
    monkeypatch.setattr(settings, "login_rate_limit_per_hour", 100)
    _install_throttle(monkeypatch, _FakeRedis())

    wrong = {"username": user.username, "password": "wrong"}
    assert client.post("/api/v1/auth/login", json=wrong).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": user.username, "password": "unit-test-password"},
        ).status_code
        == 200
    )

    # 成功登录清零计数：随后两次失败仍是 401，而不是直接 429
    assert client.post("/api/v1/auth/login", json=wrong).status_code == 401
    assert client.post("/api/v1/auth/login", json=wrong).status_code == 401
    assert client.post("/api/v1/auth/login", json=wrong).status_code == 429


def test_login_throttle_fails_open_when_redis_down(client, user_factory, monkeypatch):
    user = user_factory(f"auth-redis-down-{uuid.uuid4().hex[:6]}")
    monkeypatch.setattr(settings, "login_rate_limit_per_minute", 1)
    monkeypatch.setattr(settings, "login_rate_limit_per_hour", 1)
    _install_throttle(monkeypatch, _BrokenRedis())

    # Redis 不可用时不能把所有人挡在门外：仍是凭据错误 401，而不是 429
    for _ in range(2):
        response = client.post(
            "/api/v1/auth/login",
            json={"username": user.username, "password": "wrong"},
        )
        assert response.status_code == 401
