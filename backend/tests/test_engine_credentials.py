"""系统内填写 AI 平台密钥：加密落库、接口不回显、可清除回落环境变量。"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.secrets_box import decrypt_secret, encrypt_secret, has_encrypted_secret
from app.core.security import create_access_token
from app.models import AiEngine, AiEngineEntry
from app.models.enums import EngineProtocol
from app.services.engine_credentials import credential_source, resolve_entry_secret


def auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _make_engine(db) -> AiEngine:
    row = AiEngine(
        code=f"eng-{uuid.uuid4().hex[:6]}",
        name="测试平台",
        vendor="测试厂商",
        supports_search=False,
        supports_citation=False,
        is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def _create_entry(client, db, user, **overrides):
    engine = _make_engine(db)
    payload = {
        "entry_type": "api",
        "name": "DeepSeek 官方 API",
        "entry_url": "https://api.deepseek.com/v1",
        "protocol": "openai_compatible",
        "model_name": "deepseek-chat",
        "credential_ref": None,
        "supports_search": False,
    }
    payload.update(overrides)
    response = client.post(
        f"/api/v1/engines/{engine.id}/entries", json=payload, headers=auth(user)
    )
    assert response.status_code == 201, response.text
    return engine, response


def test_secret_box_roundtrip_and_invalid_token_returns_empty(monkeypatch):
    cipher = encrypt_secret("sk-very-secret")
    assert cipher.startswith("v1:")
    assert "sk-very-secret" not in cipher
    assert has_encrypted_secret(cipher) is True
    assert decrypt_secret(cipher) == "sk-very-secret"
    # 换密钥/篡改密文解密失败一律返回空串，交由调用方回落环境变量
    assert decrypt_secret("v1:not-a-valid-token") == ""
    assert decrypt_secret("plain-text") == ""
    assert decrypt_secret(None) == ""
    assert encrypt_secret("   ") == ""


def test_stored_secret_wins_over_environment(monkeypatch, db):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    entry = AiEngineEntry(
        engine_id=_make_engine(db).id,
        entry_type="api",
        name="带密文入口",
        entry_url="https://api.deepseek.com/v1",
        protocol=EngineProtocol.OPENAI_COMPATIBLE,
        model_name="deepseek-chat",
        credential_ref="DEEPSEEK_API_KEY",
        encrypted_secret=encrypt_secret("stored-key"),
        supports_search=False,
        is_active=True,
    )
    db.add(entry)
    db.flush()
    assert resolve_entry_secret(entry) == "stored-key"
    assert credential_source(entry) == "database"
    entry.encrypted_secret = None
    assert resolve_entry_secret(entry) == "env-key"
    assert credential_source(entry) == "environment"


def test_create_entry_with_api_key_is_encrypted_and_not_echoed(client, db, user_factory, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    engine, response = _create_entry(client, db, admin, api_key="sk-live-secret")

    data = response.json()["data"]
    assert data["credential_configured"] is True
    assert data["credential_source"] == "database"
    assert data["credential_updated_at"] is not None
    assert "sk-live-secret" not in response.text

    row = db.scalar(select(AiEngineEntry).where(AiEngineEntry.engine_id == engine.id))
    assert row is not None
    assert row.encrypted_secret and row.encrypted_secret != "sk-live-secret"
    assert row.encrypted_secret.startswith("v1:")
    assert decrypt_secret(row.encrypted_secret) == "sk-live-secret"


def test_patch_clear_api_key_falls_back_to_environment(client, db, user_factory, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-fallback")
    admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    engine, response = _create_entry(
        client, db, admin, credential_ref="DEEPSEEK_API_KEY", api_key="stored-secret"
    )
    entry_id = response.json()["data"]["id"]
    assert response.json()["data"]["credential_source"] == "database"

    cleared = client.patch(
        f"/api/v1/engines/{engine.id}/entries/{entry_id}",
        json={"clear_api_key": True},
        headers=auth(admin),
    )
    assert cleared.status_code == 200, cleared.text
    data = cleared.json()["data"]
    assert data["credential_source"] == "environment"
    assert data["credential_configured"] is True
    row = db.scalar(select(AiEngineEntry).where(AiEngineEntry.id == uuid.UUID(entry_id)))
    assert row.encrypted_secret is None


def test_api_key_whitespace_and_conflict_are_rejected(client, db, user_factory):
    admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    engine = _make_engine(db)
    base = {
        "entry_type": "api",
        "name": "带空白密钥的入口",
        "entry_url": "https://api.deepseek.com/v1",
        "protocol": "openai_compatible",
        "model_name": "deepseek-chat",
        "credential_ref": None,
    }
    response = client.post(
        f"/api/v1/engines/{engine.id}/entries",
        json={**base, "api_key": " sk-padded "},
        headers=auth(admin),
    )
    assert response.status_code == 422

    entry_id = _create_entry(client, db, admin)[1].json()["data"]["id"]
    conflict = client.patch(
        f"/api/v1/engines/{engine.id}/entries/{entry_id}",
        json={"clear_api_key": True, "api_key": "sk-both"},
        headers=auth(admin),
    )
    assert conflict.status_code == 422


def test_yuanbao_secondary_secret_is_encrypted(client, db, user_factory, monkeypatch):
    monkeypatch.delenv("YUANBAO_SECRET_ID", raising=False)
    monkeypatch.delenv("YUANBAO_SECRET_KEY", raising=False)
    admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    engine, response = _create_entry(
        client,
        db,
        admin,
        name="腾讯元宝 SearchPro",
        entry_url="https://wsa.tencentcloudapi.com",
        protocol="yuanbao_search",
        model_name="yuanbao-search",
        credential_ref=None,
        api_key="AKIDSECRET",
        api_key_secondary="SECRETKEYVALUE",
        supports_search=True,
    )
    data = response.json()["data"]
    assert data["protocol"] == "yuanbao_search"
    assert data["credential_configured"] is True
    assert data["credential_source"] == "database"
    assert "SECRETKEYVALUE" not in response.text

    row = db.scalar(select(AiEngineEntry).where(AiEngineEntry.engine_id == engine.id))
    assert decrypt_secret(row.encrypted_secret_secondary) == "SECRETKEYVALUE"
