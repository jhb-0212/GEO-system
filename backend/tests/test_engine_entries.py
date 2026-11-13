"""AI 平台入口自助配置与连通性测试：只验证配置/协议，不触达真实平台。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models import AiEngine, AiEngineEntry, AuditLog
from app.models.enums import EngineEntryType, EngineProtocol
from app.services.engine_connectors import test_entry_connection as probe_entry_connection
from app.services.monitoring_collection import (
    AccessBlockedFailure,
    UnconfiguredAdapter,
    build_entry_adapter,
)
from app.services.openai_compatible_adapter import OpenAICompatibleAdapter


def auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _make_engine(db, *, code: str | None = None) -> AiEngine:
    row = AiEngine(
        code=code or f"eng-{uuid.uuid4().hex[:6]}",
        name="测试平台",
        vendor="测试厂商",
        supports_search=False,
        supports_citation=False,
        is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def _make_entry(
    db,
    engine: AiEngine,
    *,
    protocol: EngineProtocol = EngineProtocol.OPENAI_COMPATIBLE,
    entry_type: EngineEntryType = EngineEntryType.API,
    name: str = "测试入口",
    credential_ref: str | None = "DEEPSEEK_API_KEY",
) -> AiEngineEntry:
    row = AiEngineEntry(
        engine_id=engine.id,
        entry_type=entry_type,
        name=name,
        entry_url="https://api.deepseek.com/v1",
        protocol=protocol,
        model_name="deepseek-chat",
        credential_ref=credential_ref,
        supports_search=False,
        is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def test_engine_manage_can_create_entry(client, db, user_factory):
    engine = _make_engine(db)
    sys_admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    response = client.post(
        f"/api/v1/engines/{engine.id}/entries",
        json={
            "entry_type": "api",
            "name": "DeepSeek 官方 API",
            "entry_url": "https://api.deepseek.com/v1",
            "protocol": "openai_compatible",
            "model_name": "deepseek-chat",
            "credential_ref": "DEEPSEEK_API_KEY",
            "supports_search": False,
        },
        headers=auth(sys_admin),
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["protocol"] == "openai_compatible"
    assert data["credential_ref"] == "DEEPSEEK_API_KEY"
    assert data["credential_configured"] is False
    assert "api_key" not in data
    assert "password" not in data


def test_engine_manage_rejects_project_editor(client, db, user_factory):
    engine = _make_engine(db)
    editor = user_factory(f"editor-{uuid.uuid4().hex[:6]}")
    response = client.post(
        f"/api/v1/engines/{engine.id}/entries",
        json={"name": "无权限入口", "protocol": "openai_compatible"},
        headers=auth(editor),
    )
    assert response.status_code == 403


def test_patch_entry_and_test_connection_success(client, db, user_factory, monkeypatch):
    engine = _make_engine(db)
    entry = _make_entry(db, engine)
    sys_admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)

    monkeypatch.setattr(
        "app.api.engines.test_entry_connection",
        lambda _entry: {
            "success": True,
            "protocol": "openai_compatible",
            "endpoint": "https://api.deepseek.com/v1/chat/completions",
            "model_name": "deepseek-chat",
            "latency_ms": 12.3,
            "error_code": None,
            "message": "连接成功",
            "checked_at": datetime.now(timezone.utc),
        },
    )
    response = client.post(
        f"/api/v1/engines/{engine.id}/entries/{entry.id}/test-connection",
        headers=auth(sys_admin),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["success"] is True
    db.refresh(entry)
    assert entry.last_verified_at is not None
    audit = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "engine.entry.test",
            AuditLog.target_id == entry.id,
        )
    )
    assert audit is not None


def test_connection_service_success_without_reading_answer():
    entry = SimpleNamespace(
        protocol=EngineProtocol.OPENAI_COMPATIBLE,
        entry_url="https://api.deepseek.com/v1",
        model_name="deepseek-chat",
        credential_ref=None,
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_entry_connection(entry, client=client)
    assert result["success"] is True
    assert result["error_code"] is None
    assert result["latency_ms"] is not None
    assert "pong" not in result["message"]


def test_connection_service_classifies_auth_and_rate_limit():
    entry = SimpleNamespace(
        protocol=EngineProtocol.OPENAI_COMPATIBLE,
        entry_url="https://api.deepseek.com/v1",
        model_name="deepseek-chat",
        credential_ref=None,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(401)
        return httpx.Response(429)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_entry_connection(entry, client=client)
    assert result["error_code"] == "auth_failed"


def test_connection_service_rejects_unsupported_protocol():
    entry = SimpleNamespace(
        protocol=EngineProtocol.CUSTOM,
        entry_url="https://example.com/v1",
        model_name="m",
        credential_ref=None,
    )
    result = probe_entry_connection(entry)
    assert result["success"] is False
    assert result["error_code"] == "unsupported_protocol"


def test_adapter_factory_selects_openai_and_custom(db, monkeypatch):
    engine = _make_engine(db)
    custom = _make_entry(db, engine, protocol=EngineProtocol.CUSTOM, name="自定义入口")
    assert isinstance(build_entry_adapter(db, custom), UnconfiguredAdapter)

    openai = _make_entry(db, engine, name="OpenAI 入口")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    adapter = build_entry_adapter(db, openai)
    assert isinstance(adapter, OpenAICompatibleAdapter)
    assert adapter.model == "deepseek-chat"

    monkeypatch.delenv("DEEPSEEK_API_KEY")
    with pytest.raises(AccessBlockedFailure):
        build_entry_adapter(db, openai)


def _probe_entry(**overrides):
    base = {
        "protocol": EngineProtocol.OPENAI_COMPATIBLE,
        "entry_url": "https://api.deepseek.com/v1",
        "model_name": "deepseek-chat",
        "credential_ref": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_connection_service_validates_missing_fields(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert probe_entry_connection(_probe_entry(entry_url=None))["error_code"] == "entry_url_missing"
    assert probe_entry_connection(_probe_entry(model_name=None))["error_code"] == "model_name_missing"
    assert (
        probe_entry_connection(_probe_entry(credential_ref="DEEPSEEK_API_KEY"))["error_code"]
        == "credential_missing"
    )


def test_connection_service_classifies_network_errors():
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        result = probe_entry_connection(_probe_entry(), client=client)
    assert result["error_code"] == "timeout"

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with httpx.Client(transport=httpx.MockTransport(unreachable)) as client:
        result = probe_entry_connection(_probe_entry(), client=client)
    assert result["error_code"] == "unreachable"


@pytest.mark.parametrize(
    "status, code",
    [
        (404, "endpoint_not_found"),
        (500, "upstream_error"),
        (400, "http_error"),
        (429, "rate_limited"),
    ],
)
def test_connection_service_classifies_http_status(status, code):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_entry_connection(_probe_entry(), client=client)
    assert result["success"] is False
    assert result["error_code"] == code


def test_list_and_patch_entry(client, db, user_factory):
    engine = _make_engine(db)
    entry = _make_entry(db, engine)
    sys_admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    headers = auth(sys_admin)

    listed = client.get(f"/api/v1/engines/{engine.id}/entries", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["meta"]["total"] == 1

    patched = client.patch(
        f"/api/v1/engines/{engine.id}/entries/{entry.id}",
        json={"access_note": "运营已核验", "model_name": "deepseek-chat"},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["access_note"] == "运营已核验"


def test_entry_create_validation_and_conflict(client, db, user_factory):
    engine = _make_engine(db)
    sys_admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    headers = auth(sys_admin)

    bad_url = client.post(
        f"/api/v1/engines/{engine.id}/entries",
        json={"name": "bad-url", "entry_url": "ftp://example.com"},
        headers=headers,
    )
    assert bad_url.status_code == 422

    bad_ref = client.post(
        f"/api/v1/engines/{engine.id}/entries",
        json={"name": "bad-ref", "credential_ref": "sk-plaintext"},
        headers=headers,
    )
    assert bad_ref.status_code == 422

    missing_model = client.post(
        f"/api/v1/engines/{engine.id}/entries",
        json={
            "name": "missing-model",
            "entry_url": "https://api.deepseek.com/v1",
            "protocol": "openai_compatible",
            "is_active": True,
        },
        headers=headers,
    )
    assert missing_model.status_code == 400
    assert missing_model.json()["error"]["code"] == "model_name_missing"

    payload = {
        "name": "duplicate",
        "entry_url": "https://api.deepseek.com/v1",
        "protocol": "openai_compatible",
        "model_name": "deepseek-chat",
    }
    assert client.post(f"/api/v1/engines/{engine.id}/entries", json=payload, headers=headers).status_code == 201
    duplicate = client.post(f"/api/v1/engines/{engine.id}/entries", json=payload, headers=headers)
    assert duplicate.status_code == 400
    assert duplicate.json()["error"]["code"] == "engine_entry_exists"


def test_entry_missing_engine_or_entry(client, db, user_factory):
    sys_admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    headers = auth(sys_admin)
    missing = uuid.uuid4()
    assert client.get(f"/api/v1/engines/{missing}/entries", headers=headers).status_code == 404

    engine = _make_engine(db)
    assert (
        client.patch(
            f"/api/v1/engines/{engine.id}/entries/{uuid.uuid4()}",
            json={"access_note": "x"},
            headers=headers,
        ).status_code
        == 404
    )
