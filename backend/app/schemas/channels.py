"""渠道台账写接口请求模型：新增与局部更新。"""

from pydantic import BaseModel, Field, field_validator

from app.models.enums import ChannelCategory, ChannelStatus


def _normalize_domain(value: str | None) -> str | None:
    """域名存库统一小写；允许空值，但不接受 URL、路径或空格。"""
    if value is None:
        return None
    clean = value.strip().lower().rstrip(".")
    if not clean:
        return None
    if "://" in clean or "/" in clean or " " in clean:
        raise ValueError("domain 必须是纯域名，不能包含协议、路径或空格")
    if len(clean) > 255:
        raise ValueError("domain 长度不能超过 255")
    return clean


def _normalize_http_url(value: str | None, label: str) -> str | None:
    """发布入口只接受 http/https 绝对地址，空值表示未配置。"""
    if value is None:
        return None
    clean = value.strip()
    if not clean:
        return None
    if not clean.startswith(("http://", "https://")):
        raise ValueError(f"{label} 必须是 http/https 地址")
    if len(clean) > 512:
        raise ValueError(f"{label} 长度不能超过 512")
    return clean


class ChannelCreate(BaseModel):
    """新增渠道：code 在项目内唯一，旧域名可先放进 aliases。"""

    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=128)
    category: ChannelCategory
    status: ChannelStatus = ChannelStatus.CANDIDATE
    primary_domain: str | None = Field(default=None, max_length=255)
    publish_url: str | None = Field(default=None, max_length=512)
    login_url: str | None = Field(default=None, max_length=512)
    notes: str | None = Field(default=None, max_length=5000)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("primary_domain")
    @classmethod
    def normalize_primary_domain(cls, value: str | None) -> str | None:
        return _normalize_domain(value)

    @field_validator("publish_url")
    @classmethod
    def normalize_publish_url(cls, value: str | None) -> str | None:
        return _normalize_http_url(value, "发布后台地址")

    @field_validator("login_url")
    @classmethod
    def normalize_login_url(cls, value: str | None) -> str | None:
        return _normalize_http_url(value, "登录地址")

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, values: list[str]) -> list[str]:
        normalized = {_normalize_domain(value) for value in values}
        normalized.discard(None)
        return sorted(normalized)


class ChannelUpdate(BaseModel):
    """局部更新：code 不允许改；旧名称和旧主域名由服务端转别名保留。"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    category: ChannelCategory | None = None
    status: ChannelStatus | None = None
    primary_domain: str | None = Field(default=None, max_length=255)
    publish_url: str | None = Field(default=None, max_length=512)
    login_url: str | None = Field(default=None, max_length=512)
    notes: str | None = Field(default=None, max_length=5000)
    aliases: list[str] | None = Field(default=None, max_length=50)
    is_active: bool | None = None

    @field_validator("primary_domain")
    @classmethod
    def normalize_primary_domain(cls, value: str | None) -> str | None:
        return _normalize_domain(value)

    @field_validator("publish_url")
    @classmethod
    def normalize_publish_url(cls, value: str | None) -> str | None:
        return _normalize_http_url(value, "发布后台地址")

    @field_validator("login_url")
    @classmethod
    def normalize_login_url(cls, value: str | None) -> str | None:
        return _normalize_http_url(value, "登录地址")

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized = {_normalize_domain(value) for value in values}
        normalized.discard(None)
        return sorted(normalized)
