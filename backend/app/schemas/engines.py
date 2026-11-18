"""AI 平台入口维护请求模型：支持系统内填写 API Key（加密落库、不回显）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.credentials import CREDENTIAL_REF_PATTERN
from app.models.enums import EngineEntryType, EngineProtocol
from app.services.engine_url_policy import validate_engine_url

ENV_NAME_PATTERN = CREDENTIAL_REF_PATTERN
CREDENTIAL_REF_HINT = (
    "credential_ref 只接受受控密钥变量名：大写字母/数字/下划线，且以 "
    "_API_KEY、_SECRET_KEY、_SECRET_ID、_ACCESS_KEY 或 _TOKEN 结尾（如 DEEPSEEK_API_KEY）"
)
API_KEY_HINT = "api_key 是密钥明文，只用于写入；不接受首尾空白，长度 1–4096"


def _clean_api_key(value: str | None) -> str | None:
    """写入用的密钥明文：空串视为未传；首尾空白拒绝（避免复制时夹带不可见字符）。"""
    if value is None:
        return None
    if not value:
        return None
    if value != value.strip():
        raise ValueError(API_KEY_HINT)
    if len(value) > 4096:
        raise ValueError(API_KEY_HINT)
    return value


class EngineEntryCreate(BaseModel):
    entry_type: EngineEntryType = EngineEntryType.API
    name: str = Field(min_length=1, max_length=64)
    entry_url: str | None = Field(default=None, max_length=2048)
    protocol: EngineProtocol = EngineProtocol.CUSTOM
    model_name: str | None = Field(default=None, max_length=128)
    credential_ref: str | None = Field(default=None, max_length=64)
    # 系统内直接填写的密钥（加密落库）；与 credential_ref 并存时以库内密文优先。
    api_key: str | None = Field(default=None, max_length=4096)
    api_key_secondary: str | None = Field(default=None, max_length=4096)
    supports_search: bool = False
    access_note: str | None = Field(default=None, max_length=2000)
    is_active: bool = True

    @field_validator("entry_url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            return None
        if not clean.startswith(("http://", "https://")):
            raise ValueError("entry_url 必须以 http:// 或 https:// 开头")
        return clean

    @model_validator(mode="after")
    def _validate_endpoint(self) -> "EngineEntryCreate":
        if self.entry_url:
            validate_engine_url(self.entry_url, self.protocol)
        return self

    @field_validator("credential_ref")
    @classmethod
    def _credential_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            return None
        if not ENV_NAME_PATTERN.match(clean):
            raise ValueError(CREDENTIAL_REF_HINT)
        return clean

    @field_validator("api_key", "api_key_secondary")
    @classmethod
    def _api_key(cls, value: str | None) -> str | None:
        return _clean_api_key(value)


class EngineEntryVerify(BaseModel):
    """用户端 / 应用内搜索入口的人工核验记录。"""

    verified_at: datetime | None = None
    note: str | None = Field(default=None, max_length=500)


class EngineEntryUpdate(BaseModel):
    """PATCH 语义：未传字段不变，显式 null 清空可空字段。"""

    entry_type: EngineEntryType | None = None
    name: str | None = Field(default=None, min_length=1, max_length=64)
    entry_url: str | None = Field(default=None, max_length=2048)
    protocol: EngineProtocol | None = None
    model_name: str | None = Field(default=None, max_length=128)
    credential_ref: str | None = Field(default=None, max_length=64)
    # 传了 api_key 就覆盖系统内保存的密钥；留空表示不改。
    api_key: str | None = Field(default=None, max_length=4096)
    api_key_secondary: str | None = Field(default=None, max_length=4096)
    # 显式清除系统内保存的密钥（改回走环境变量时用）。
    clear_api_key: bool = False
    supports_search: bool | None = None
    access_note: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None

    @field_validator("entry_url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            return None
        if not clean.startswith(("http://", "https://")):
            raise ValueError("entry_url 必须以 http:// 或 https:// 开头")
        return clean

    @model_validator(mode="after")
    def _validate_endpoint(self) -> "EngineEntryUpdate":
        if self.entry_url and self.protocol is not None:
            validate_engine_url(self.entry_url, self.protocol)
        return self

    @field_validator("credential_ref")
    @classmethod
    def _credential_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            return None
        if not ENV_NAME_PATTERN.match(clean):
            raise ValueError(CREDENTIAL_REF_HINT)
        return clean

    @field_validator("api_key", "api_key_secondary")
    @classmethod
    def _api_key(cls, value: str | None) -> str | None:
        return _clean_api_key(value)

    @model_validator(mode="after")
    def _clear_conflict(self) -> "EngineEntryUpdate":
        if self.clear_api_key and (self.api_key or self.api_key_secondary):
            raise ValueError("clear_api_key 与 api_key 不能同时传")
        return self
