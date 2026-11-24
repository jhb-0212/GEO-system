"""配额告警：只在级别升高时写审计/外发；跨客户总览给出健康度。"""

import uuid

from sqlalchemy import func, select

from app.core.security import create_access_token
from app.models import AuditLog
from app.services import quota_alerts


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _create_org_project(client, root, suffix: str) -> tuple[str, str]:
    org = client.post(
        "/api/v1/organizations", headers=_auth(root),
        json={"code": f"qa-{suffix}", "name": "告警客户"},
    ).json()["data"]
    project = client.post(
        "/api/v1/projects", headers=_auth(root),
        json={"code": f"qa-p-{suffix}", "name": "告警项目", "organization_id": org["id"]},
    ).json()["data"]
    return org["id"], project["id"]


def test_quota_alert_only_on_level_increase(client, db, user_factory, monkeypatch):
    suffix = uuid.uuid4().hex[:6]
    root = user_factory(f"qa-root-{suffix}", is_system_admin=True)
    org_id, project_id = _create_org_project(client, root, suffix)
    sent: list[dict] = []
    monkeypatch.setattr(quota_alerts, "_post", lambda payload: sent.append(payload))

    def set_quota(value: int) -> None:
        client.put(
            f"/api/v1/projects/{project_id}/organization", headers=_auth(root),
            json={"quotas": {"projects": value}},
        )

    set_quota(1)  # 已用 1/1 → exceeded
    set_quota(1)  # 同级重复，不重复推送
    set_quota(3)  # 33%，回落：只清状态
    set_quota(2)  # 1/2 = 50%，无告警
    set_quota(1)  # 再次 exceeded：算一次新的

    audits = db.scalar(
        select(func.count(AuditLog.id)).where(
            AuditLog.action == "organization.quota_alert",
            AuditLog.project_id == uuid.UUID(project_id),
        )
    )
    assert audits == 2
    assert len(sent) == 2
    assert sent[-1]["event"] == "organization.quota_alert"
    assert "已达上限" in sent[-1]["message"]


def test_organizations_overview_reports_health(client, user_factory, monkeypatch):
    from app.core.config import settings

    suffix = uuid.uuid4().hex[:6]
    root = user_factory(f"qa-ov-{suffix}", is_system_admin=True)
    org_id, project_id = _create_org_project(client, root, suffix)
    client.put(
        f"/api/v1/projects/{project_id}/organization", headers=_auth(root),
        json={"quotas": {"projects": 1, "members": 5}},
    )
    monkeypatch.setattr(settings, "quota_alert_webhook", "https://example.invalid/hook")

    data = client.get("/api/v1/organizations/overview", headers=_auth(root)).json()["data"]
    row = next(item for item in data["organizations"] if item["id"] == org_id)
    assert row["health"] == "exceeded"
    assert row["quotas"]["projects"] == 1
    assert row["alerts"][0]["key"] == "projects"
    assert data["webhook_configured"] is True


def test_quota_alert_feishu_payload(monkeypatch):
    import json

    from app.core.config import settings

    captured: list[dict] = []
    monkeypatch.setattr(settings, "quota_alert_webhook", "https://example.invalid/hook")
    monkeypatch.setattr(settings, "quota_alert_format", "feishu")

    class _Response:
        def read(self) -> bytes:
            return b"{}"

    def fake_urlopen(request, timeout=0):
        captured.append(json.loads(request.data.decode("utf-8")))
        return _Response()

    monkeypatch.setattr(quota_alerts.urllib.request, "urlopen", fake_urlopen)
    quota_alerts._post({"event": "organization.quota_alert", "message": "客户项目数 已达上限 5/5"})

    assert captured[0]["msg_type"] == "text"
    assert "客户项目数" in captured[0]["content"]["text"]


def test_quota_alert_reaches_real_http_webhook(monkeypatch):
    """起一个真 HTTP 端口，验证编码、请求头与 body 能过真实 urllib 通路。"""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from app.core.config import settings

    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            received.append({
                "content_type": self.headers.get("Content-Type"),
                "body": json.loads(self.rfile.read(length).decode("utf-8")),
            })
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr(settings, "quota_alert_webhook", f"http://127.0.0.1:{server.server_port}/hook")
        monkeypatch.setattr(settings, "quota_alert_format", "generic")
        quota_alerts._post({"event": "organization.quota_alert", "message": "客户项目数 已达上限 1/1"})
    finally:
        server.shutdown()
        server.server_close()

    assert received and received[0]["body"]["event"] == "organization.quota_alert"
    assert received[0]["content_type"].startswith("application/json")


def test_quota_alert_dingtalk_signature_over_real_http(monkeypatch):
    """钉钉机器人：body 用 msgtype，签名放在 URL 查询参数，走真实 urllib。"""
    import base64
    import hashlib
    import hmac
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import parse_qs, urlsplit

    from app.core.config import settings

    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            received.append({
                "query": parse_qs(urlsplit(self.path).query),
                "body": json.loads(self.rfile.read(length).decode("utf-8")),
            })
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"errcode":0}')

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr(settings, "quota_alert_webhook", f"http://127.0.0.1:{server.server_port}/robot/send")
        monkeypatch.setattr(settings, "quota_alert_format", "dingtalk")
        monkeypatch.setattr(settings, "quota_alert_secret", "ding-secret")
        quota_alerts._post({"event": "organization.quota_alert", "message": "客户成员数 已达上限 3/3"})
    finally:
        server.shutdown()
        server.server_close()

    assert received
    assert received[0]["body"]["msgtype"] == "text"
    assert "客户成员数" in received[0]["body"]["text"]["content"]
    timestamp = received[0]["query"]["timestamp"][0]
    sign = received[0]["query"]["sign"][0]
    expected = base64.b64encode(
        hmac.new(
            b"ding-secret", f"{timestamp}\nding-secret".encode("utf-8"), digestmod=hashlib.sha256
        ).digest()
    ).decode("utf-8")
    assert sign == expected


def test_quota_alert_wecom_text_over_real_http(monkeypatch):
    """企业微信机器人：固定 msgtype=text，key 保留在部署方给的 URL 上。"""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlsplit

    from app.core.config import settings

    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            received.append({
                "path": urlsplit(self.path).path,
                "query": urlsplit(self.path).query,
                "body": json.loads(self.rfile.read(length).decode("utf-8")),
            })
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"errcode":0}')

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr(
            settings,
            "quota_alert_webhook",
            f"http://127.0.0.1:{server.server_port}/cgi-bin/webhook/send?key=test-key",
        )
        monkeypatch.setattr(settings, "quota_alert_format", "wecom")
        quota_alerts._post({"event": "organization.quota_alert", "message": "客户项目数 已达 80%"})
    finally:
        server.shutdown()
        server.server_close()

    assert received
    assert received[0]["body"]["msgtype"] == "text"
    assert "客户项目数" in received[0]["body"]["text"]["content"]
    assert received[0]["query"] == "key=test-key"
