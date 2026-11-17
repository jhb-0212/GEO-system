"""AI 平台入口维护请求模型：运营自助只填配置，不填 API Key 明文。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.core.credentials import CREDENTIAL_REF_PATTERN
from app.models.enums import EngineEntryType, EngineProtocol

ENV_NAME_PATTERN = CREDENTIAL_REF_PATTERN
CREDENTIAL_REF_HINT = (
    "credential_ref 只接受受控密钥变量名：大写字母/数字/下划线，且以 "
    "_API_KEY、_SECRET_KEY、_SECRET_ID、_ACCESS_KEY 或 _TOKEN 结尾（如 DEEPSEEK_API_KEY）"
)


class EngineEntryCreate(BaseModel):
    entry_type: EngineEntryType = EngineEntryType.API
    name: str = Field(min_length=1, max_length=64)
    entry_url: str | None = Field(default=None, max_length=2048)
    protocol: EngineProtocol = EngineProtocol.CUSTOM
    model_name: str | None = Field(default=None, max_length=128)
    credential_ref: str | None = Field(default=None, max_length=64)
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
