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


class _FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key, seconds):
        return True


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
