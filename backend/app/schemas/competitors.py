"""竞品台账请求模型：竞品名在项目内唯一，用于答案提及归因与 Share of Voice。"""

import re
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

# 最终落库只保存主机名：字母/数字/连字符/点；输入允许完整网址，由 _normalize_domain 提取。
_DOMAIN_PATTERN = re.compile(
    r"^(?=.{1,255}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])$"
)
_SCHEME_PREFIX = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)


def _normalize_domain(value: str | None) -> str | None:
    """接受裸域名或完整网址，统一提取主机名；路径、参数、端口和协议不会落库。"""
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    candidate = f"https:{raw}" if raw.startswith("//") else raw if _SCHEME_PREFIX.match(raw) else f"https://{raw}"
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("只支持 http:// 或 https:// 网址")
    host = (parsed.hostname or "").rstrip(".").lower()
    if not host:
        raise ValueError("请输入有效网址，如 https://rival.example.com")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("无法从网址中识别有效域名") from exc
    if len(host) > 255:
        raise ValueError("域名不能超过 255 字")
    if not _DOMAIN_PATTERN.fullmatch(host):
        raise ValueError("无法从网址中识别有效域名")
    return host


class CompetitorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    domain: str | None = Field(default=None, max_length=2048)
    notes: str | None = Field(default=None, max_length=5000)
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("不能为空")
        if any(char in clean for char in "\r\n\t"):
            raise ValueError("不能包含换行、回车或制表符")
        return clean

    @field_validator("domain")
    @classmethod
    def clean_domain(cls, value: str | None) -> str | None:
        return _normalize_domain(value)


class CompetitorUpdate(BaseModel):
    """局部更新；显式 null 清空可空字段，不传保持原值。"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    domain: str | None = Field(default=None, max_length=2048)
    notes: str | None = Field(default=None, max_length=5000)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            raise ValueError("不能为空")
        if any(char in clean for char in "\r\n\t"):
            raise ValueError("不能包含换行、回车或制表符")
        return clean

    @field_validator("domain")
    @classmethod
    def clean_domain(cls, value: str | None) -> str | None:
        return _normalize_domain(value)


class CompetitorDeleted(BaseModel):
    id: str
    deleted: bool = True
