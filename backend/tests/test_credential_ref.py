"""SECRET_KEY 与 credential_ref 的收紧：非开发环境拒绝默认密钥，凭证只读白名单变量。"""

import uuid

import pytest
from pydantic import ValidationError

from app.core.config import DEV_SECRET_KEY, Settings
from app.core.credentials import is_allowed_credential_ref, read_credential_env
from app.schemas.engines import EngineEntryCreate
from app.schemas.publishing import PublishAccountCreate


def test_dev_env_allows_default_secret_key():
    settings = Settings(app_env="dev", secret_key=DEV_SECRET_KEY)
    assert settings.secret_key == DEV_SECRET_KEY


def test_production_rejects_default_secret_key():
    with pytest.raises(ValidationError):
        Settings(app_env="production", secret_key=DEV_SECRET_KEY)


def test_production_rejects_short_secret_key():
    with pytest.raises(ValidationError):
        Settings(app_env="production", secret_key="short-secret")


def test_production_accepts_strong_secret_key():
    strong = "x" * 40
    settings = Settings(app_env="production", secret_key=strong)
    assert settings.secret_key == strong


def test_read_credential_env_refuses_uncontrolled_names(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("DATABASE_URL", "postgresql://geo:secret@db/app")
    monkeypatch.setenv("SECRET_KEY", "app-signing-key")
    assert read_credential_env("PATH") == ""
    assert read_credential_env("DATABASE_URL") == ""
    assert read_credential_env("SECRET_KEY") == ""


def test_read_credential_env_reads_allowlisted_secret(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    assert is_allowed_credential_ref("DEEPSEEK_API_KEY")
    assert read_credential_env("DEEPSEEK_API_KEY") == "sk-test"
    assert read_credential_env("  DEEPSEEK_API_KEY  ") == "sk-test"


def test_engine_entry_schema_rejects_arbitrary_env_name():
    with pytest.raises(ValidationError):
        EngineEntryCreate(name="evil", credential_ref="PATH")
    entry = EngineEntryCreate(name="ok", credential_ref="DEEPSEEK_API_KEY")
    assert entry.credential_ref == "DEEPSEEK_API_KEY"


def test_publish_account_schema_rejects_arbitrary_env_name():
    with pytest.raises(ValidationError):
        PublishAccountCreate(
            channel_id=uuid.uuid4(), account_name="账号", credential_ref="SECRET_KEY"
        )
