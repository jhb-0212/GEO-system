"""平台 OAuth 通用框架测试：真实 HTTP 假 provider + 真实数据库事务。

覆盖：授权 URL/PKCE/state、回调兑换、令牌加密、一次性 state、刷新、撤销、
权限拒绝、未配置 provider。不依赖任何真实平台凭据。
"""

from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token
from app.core.secrets_box import decrypt_secret
from app.models import AuditLog, OAuthAuthorizationState, OAuthConnection
from app.models.enums import OAuthConnectionStatus, RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


@pytest.fixture()
def fake_provider(monkeypatch):
    calls: dict[str, dict[str, list[str]]] = {"token": {}, "userinfo": {}, "revoke": {}}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # noqa: N802
            pass

        def _json(self, payload: dict, status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            form = {key: values[0] for key, values in parse_qs(self.rfile.read(length).decode("utf-8")).items()}
            if self.path == "/token":
                calls["token"].update(form)
                if form.get("grant_type") == "refresh_token":
                    self._json({
                        "access_token": "access-2",
                        "refresh_token": "refresh-2",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                        "scope": "read write",
                    })
                else:
                    self._json({
                        "access_token": "access-1",
                        "refresh_token": "refresh-1",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                        "scope": "read write",
                    })
                return
            if self.path == "/revoke":
                calls["revoke"].update(form)
                self.send_response(200)
                self.end_headers()
                return
            self._json({"error": "not found"}, 404)

        def do_GET(self):  # noqa: N802
            if self.path.startswith("/userinfo"):
                calls["userinfo"]["authorization"] = self.headers.get("Authorization", "")
                self._json({
                    "sub": "external-001",
                    "name": "外部运营账号",
                    "email": "ops@example.com",
                })
                return
            self._json({"error": "not found"}, 404)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"

    providers = [{
        "code": "fake",
        "name": "假平台",
        "client_id": "client-id",
        "client_secret": "client-secret",
        "authorize_url": f"{base_url}/authorize",
        "token_url": f"{base_url}/token",
        "userinfo_url": f"{base_url}/userinfo",
        "revoke_url": f"{base_url}/revoke",
        "scopes": ["read", "write"],
        "user_id_path": "sub",
        "user_name_path": "name",
        "user_email_path": "email",
    }]
    monkeypatch.setattr(settings, "oauth_providers_json", json.dumps(providers, ensure_ascii=False))
    monkeypatch.setattr(settings, "oauth_providers_file", "")
    monkeypatch.setattr(settings, "oauth_callback_base_url", "http://testserver")
    monkeypatch.setattr(settings, "oauth_frontend_base_url", "http://frontend.test")
    monkeypatch.setattr(settings, "oauth_http_timeout_seconds", 2.0)
    monkeypatch.setattr(settings, "oauth_state_expire_minutes", 10)

    try:
        yield base_url, calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_oauth_authorize_callback_refresh_revoke(client, db, user_factory, project_factory, member_factory, fake_provider):
    base_url, calls = fake_provider
    user = user_factory("oauth-editor")
    project = project_factory(f"oauth-{uuid.uuid4().hex[:6]}")
    member_factory(project, user, RoleCode.EDITOR)
    headers = _auth(user)

    providers = client.get(f"/api/v1/projects/{project.id}/oauth/providers", headers=headers)
    assert providers.status_code == 200
    assert providers.json()["data"][0]["code"] == "fake"

    authorized = client.post(
        f"/api/v1/projects/{project.id}/oauth/authorize",
        headers=headers,
        json={"provider_code": "fake", "return_path": "/workbench?section=publishing"},
    )
    assert authorized.status_code == 200
    payload = authorized.json()["data"]
    parsed = urlparse(payload["authorization_url"])
    query = dict(parse_qs(parsed.query))
    assert query["client_id"][0] == "client-id"
    assert query["redirect_uri"][0] == "http://testserver/api/v1/oauth/callback/fake"
    assert query["state"][0] == payload["state"]
    assert query["code_challenge_method"][0] == "S256"
    assert query["code_challenge"][0]
    assert len(payload["state"]) >= 32

    state_row = db.scalar(
        select(OAuthAuthorizationState).where(
            OAuthAuthorizationState.project_id == project.id,
            OAuthAuthorizationState.provider_code == "fake",
        )
    )
    assert state_row is not None
    assert state_row.state_hash != payload["state"]
    assert state_row.code_verifier_encrypted.startswith("v1:")
    assert len(state_row.code_verifier_encrypted) > 32
    assert base_url not in state_row.code_verifier_encrypted

    callback = client.get(
        f"/api/v1/oauth/callback/fake?code=good-code&state={payload['state']}",
        follow_redirects=False,
    )
    assert callback.status_code == 302
    location = callback.headers["location"]
    assert "oauth=connected" in location
    assert "provider=fake" in location
    assert "access-1" not in location

    connection = db.scalar(
        select(OAuthConnection).where(
            OAuthConnection.project_id == project.id,
            OAuthConnection.provider_code == "fake",
        )
    )
    assert connection is not None
    assert connection.status == OAuthConnectionStatus.CONNECTED
    assert connection.external_account_id == "external-001"
    assert connection.external_account_name == "外部运营账号"
    assert connection.access_token_encrypted.startswith("v1:")
    assert "access-1" not in (connection.access_token_encrypted or "")
    assert decrypt_secret(connection.access_token_encrypted) == "access-1"
    assert connection.refresh_token_encrypted and connection.refresh_token_encrypted.startswith("v1:")
    assert calls["token"]["grant_type"] == "authorization_code"
    assert calls["token"]["code_verifier"]
    assert calls["userinfo"]["authorization"] == "Bearer access-1"

    # state 只能消费一次；重放不能再建连接
    replay = client.get(
        f"/api/v1/oauth/callback/fake?code=good-code&state={payload['state']}",
        follow_redirects=False,
    )
    assert replay.status_code == 302
    assert "oauth_error=oauth_state_invalid" in replay.headers["location"]
    assert db.scalar(
        select(OAuthConnection).where(
            OAuthConnection.project_id == project.id,
            OAuthConnection.provider_code == "fake",
        )
    ).id == connection.id

    listed = client.get(f"/api/v1/projects/{project.id}/oauth/connections", headers=headers)
    assert listed.status_code == 200
    item = listed.json()["data"][0]
    assert item["status"] == "connected"
    assert item["has_refresh_token"] is True
    assert "access_token" not in item
    assert "refresh_token" not in item

    refreshed = client.post(
        f"/api/v1/projects/{project.id}/oauth/connections/{connection.id}/refresh",
        headers=headers,
    )
    assert refreshed.status_code == 200
    db.refresh(connection)
    assert decrypt_secret(connection.access_token_encrypted) == "access-2"
    assert decrypt_secret(connection.refresh_token_encrypted) == "refresh-2"
    assert "access-2" not in refreshed.text

    audited = db.scalar(
        select(AuditLog).where(
            AuditLog.project_id == project.id,
            AuditLog.action == "oauth.connection_refreshed",
        )
    )
    assert audited is not None

    revoked = client.post(
        f"/api/v1/projects/{project.id}/oauth/connections/{connection.id}/revoke",
        headers=headers,
    )
    assert revoked.status_code == 200
    db.refresh(connection)
    assert connection.status == OAuthConnectionStatus.REVOKED
    assert connection.access_token_encrypted is None
    assert connection.refresh_token_encrypted is None
    assert connection.revoked_at is not None
    assert calls["revoke"]["token"] == "access-2"
    assert revoked.json()["data"]["status"] == "revoked"

    revoked_refresh = client.post(
        f"/api/v1/projects/{project.id}/oauth/connections/{connection.id}/refresh",
        headers=headers,
    )
    assert revoked_refresh.status_code == 400
    assert revoked_refresh.json()["error"]["code"] == "oauth_connection_revoked"

    revoke_audit = db.scalar(
        select(AuditLog).where(
            AuditLog.project_id == project.id,
            AuditLog.action == "oauth.connection_revoked",
        )
    )
    assert revoke_audit is not None


def test_oauth_permission_and_provider_config(client, db, user_factory, project_factory, member_factory, monkeypatch):
    viewer = user_factory("oauth-viewer")
    project = project_factory(f"oauth-{uuid.uuid4().hex[:6]}")
    member_factory(project, viewer, RoleCode.VIEWER)
    headers = _auth(viewer)

    # 未配置 provider 时，读接口返回空列表，发起授权报明确错误
    monkeypatch.setattr(settings, "oauth_providers_json", "")
    monkeypatch.setattr(settings, "oauth_providers_file", "")
    providers = client.get(f"/api/v1/projects/{project.id}/oauth/providers", headers=headers)
    assert providers.status_code == 200
    assert providers.json()["data"] == []

    forbidden = client.post(
        f"/api/v1/projects/{project.id}/oauth/authorize",
        headers=headers,
        json={"provider_code": "fake"},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "insufficient_permission"

    editor = user_factory("oauth-editor-2")
    member_factory(project, editor, RoleCode.EDITOR)
    not_configured = client.post(
        f"/api/v1/projects/{project.id}/oauth/authorize",
        headers=_auth(editor),
        json={"provider_code": "fake"},
    )
    assert not_configured.status_code == 400
    assert not_configured.json()["error"]["code"] == "oauth_provider_not_configured"
