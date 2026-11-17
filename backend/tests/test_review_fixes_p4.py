"""通用审查标准整改：导出守卫、公开接口限流、密码强度。"""

import uuid

import pytest
from pydantic import ValidationError

from app.api import public as public_api
from app.core.config import settings
from app.core.errors import ExportTooLargeError
from app.core.security import create_access_token
from app.schemas.auth import PasswordChangeRequest, PasswordResetRequest
from app.services.export_guard import ensure_sync_export_allowed
from app.services.rate_limit import IpWindowLimiter


class _FakePipeline:
    """按顺序执行命令并返回结果列表，与 redis-py pipeline 的语义一致。"""

    def __init__(self, client: "_FakeRedis") -> None:
        self._client = client
        self._calls: list[tuple[str, tuple, dict]] = []

    def incr(self, key):
        self._calls.append(("incr", (key,), {}))
        return self

    def expire(self, key, seconds, nx: bool = False):
        self._calls.append(("expire", (key, seconds), {"nx": nx}))
        return self

    def execute(self):
        results = []
        for name, args, kwargs in self._calls:
            results.append(getattr(self._client, name)(*args, **kwargs))
        self._calls.clear()
        return results


class _FakeRedis:
    """最小 Redis 替身：够 IpWindowLimiter 的 `INCR` + `EXPIRE NX` 用。"""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.expirations: dict[str, int] = {}

    def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key, seconds, nx: bool = False):
        # EXPIRE NX：只在还没有过期时间时设置，否则不动。
        if nx and key in self.expirations:
            return False
        self.expirations[key] = seconds
        return True

    def pipeline(self):
        return _FakePipeline(self)


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


# ---------- 导出上限：唯一事实源 ----------


def test_export_guard_uses_single_threshold(monkeypatch):
    """等于上限放行，超过一个就拒；阈值只从配置读，调用方不再自己比较。"""
    monkeypatch.setattr(settings, "export_sync_row_limit", 10)
    ensure_sync_export_allowed(10, what="线索导出")
    with pytest.raises(ExportTooLargeError):
        ensure_sync_export_allowed(11, what="线索导出")


# ---------- 公开 FAQ 接口限流 ----------


def test_public_faq_endpoint_is_rate_limited(client, monkeypatch):
    fake = _FakeRedis()
    # 接口入口会把 settings 的最新额度写回模块级实例（热更新），所以这里两处都要设。
    monkeypatch.setattr(settings, "public_faq_per_minute", 1)
    monkeypatch.setattr(
        public_api,
        "_faq_limiter",
        IpWindowLimiter(namespace="test:public:faq", per_minute=1, client=fake),
    )

    # 项目不存在也会先过限流：第一次是 404，第二次直接被额度挡下。
    first = client.get("/api/v1/public/projects/no-such-project/faqs")
    assert first.status_code == 404

    second = client.get("/api/v1/public/projects/no-such-project/faqs")
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "public_rate_limited"


def test_ip_window_expiry_is_set_once():
    """窗口固定 90 秒：连续请求不能把过期时间一直往后推，否则计数永不清零。"""
    fake = _FakeRedis()
    limiter = IpWindowLimiter(namespace="test:expiry", per_minute=5, client=fake)
    for _ in range(3):
        limiter.consume("1.2.3.4")
    assert list(fake.expirations.values()) == [90]
    assert len(fake.counts) == 1


def test_ip_window_quota_is_hot_updatable():
    """模块级实例的额度可在请求入口写回：改配置不重启也能生效。"""
    limiter = IpWindowLimiter(namespace="test:quota", per_minute=30, client=_FakeRedis())
    limiter.per_minute = 1
    assert limiter.consume("1.1.1.1") is True
    assert limiter.consume("1.1.1.1") is False


# ---------- 密码强度 ----------


def test_password_strength_rejects_digits_and_repeats():
    with pytest.raises(ValidationError):
        PasswordResetRequest(new_password="12345678")
    with pytest.raises(ValidationError):
        PasswordChangeRequest(current_password="any", new_password="aaaaaaaa")
    assert PasswordResetRequest(new_password="geo-pass-2026").new_password == "geo-pass-2026"


def test_reset_password_api_rejects_weak_password(client, db, user_factory):
    admin = user_factory(f"sysadmin-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    target = user_factory(f"target-{uuid.uuid4().hex[:6]}")
    response = client.post(
        f"/api/v1/system/users/{target.id}/reset-password",
        json={"new_password": "12345678"},
        headers=_auth(admin),
    )
    assert response.status_code == 422
