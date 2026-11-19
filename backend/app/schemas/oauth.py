"""OAuth 授权请求模型。"""

import uuid
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator


def _safe_return_path(value: str | None) -> str:
    """只允许站内相对路径，避免回调变成开放重定向。"""
    if value is None:
        return "/workbench?section=publishing"
    clean = value.strip()
    if not clean:
        return "/workbench?section=publishing"
    if len(clean) > 512:
        raise ValueError("return_path 过长")
    if not clean.startswith("/") or clean.startswith("//") or "\\" in clean:
        raise ValueError("return_path 必须是站内相对路径")
    parsed = urlsplit(clean)
    if parsed.scheme or parsed.netloc:
        raise ValueError("return_path 不能是外部地址")
    return clean


class OAuthAuthorizeRequest(BaseModel):
    provider_code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    channel_id: uuid.UUID | None = None
    return_path: str | None = Field(default=None, max_length=512)

    @field_validator("return_path")
    @classmethod
    def _clean_return_path(cls, value: str | None) -> str:
        return _safe_return_path(value)
