"""通用 OAuth2/OIDC provider 配置。

部署方通过 `OAUTH_PROVIDERS_FILE` 或 `OAUTH_PROVIDERS_JSON` 提供 JSON；本模块只解析
配置、构造授权 URL、读取用户信息字段，不保存任何令牌。

配置示例（字段说明见 docs/OAuth平台授权接入.md）：
[
  {
    "code": "example",
    "name": "示例平台",
    "client_id": "...",
    "client_secret": "...",
    "authorize_url": "https://provider.example.com/oauth/authorize",
    "token_url": "https://provider.example.com/oauth/token",
    "userinfo_url": "https://provider.example.com/oauth/userinfo",
    "scopes": ["openid", "profile"],
    "user_id_path": "sub",
    "user_name_path": "name",
    "user_email_path": "email"
  }
]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import DEV_ENVS, settings

TokenAuthMethod = Literal["client_secret_post", "client_secret_basic"]
UserinfoAuthMethod = Literal["bearer", "query"]


class OAuthProviderConfigError(RuntimeError):
    """provider 配置缺失或非法：对外只返回配置错误，不泄露 client_secret。"""


class OAuthProvider(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=128)
    client_id: str = Field(min_length=1, max_length=512)
    client_secret: str = Field(min_length=1, max_length=1024)
    authorize_url: str
    token_url: str
    userinfo_url: str
    scopes: list[str] = Field(default_factory=list)
    authorization_params: dict[str, str] = Field(default_factory=dict)
    token_params: dict[str, str] = Field(default_factory=dict)
    token_auth_method: TokenAuthMethod = "client_secret_post"
    userinfo_method: Literal["GET", "POST"] = "GET"
    userinfo_auth: UserinfoAuthMethod = "bearer"
    # 非标准平台可用：query 参数名 -> token 响应字段名（例如微信 openid）
    userinfo_params: dict[str, str] = Field(default_factory=dict)
    # token 响应 / userinfo 响应若包在 data 下，可配置解包路径
    token_response_path: str | None = None
    userinfo_response_path: str | None = None
    user_id_path: str = "sub"
    user_name_path: str = "name"
    user_email_path: str = "email"
    revoke_url: str | None = None

    @field_validator("authorize_url", "token_url", "userinfo_url", "revoke_url")
    @classmethod
    def _validate_provider_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        parsed = urlparse(clean)
        if not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("OAuth provider URL 必须是合法绝对地址，且不能带用户名/密码")
        scheme = parsed.scheme.casefold()
        if scheme != "https":
            host = parsed.hostname.casefold()
            if not (settings.app_env.strip().lower() in DEV_ENVS and host in {"localhost", "127.0.0.1", "::1"}):
                raise ValueError("非开发环境 OAuth provider URL 必须使用 https")
        return clean

    @model_validator(mode="after")
    def _unique_scopes(self) -> "OAuthProvider":
        self.scopes = list(dict.fromkeys(scope.strip() for scope in self.scopes if scope.strip()))
        return self


def _provider_payloads() -> list[dict[str, Any]]:
    raw_file = settings.oauth_providers_file.strip()
    raw_json = settings.oauth_providers_json.strip()
    if raw_file:
        path = Path(raw_file)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OAuthProviderConfigError("OAuth provider 配置文件不可读") from exc
    elif raw_json:
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise OAuthProviderConfigError("OAuth provider JSON 配置格式错误") from exc
    else:
        return []

    if isinstance(payload, dict):
        payload = payload.get("providers", [])
    if not isinstance(payload, list):
        raise OAuthProviderConfigError("OAuth provider 配置必须是数组")
    return [item for item in payload if isinstance(item, dict)]


def configured_providers() -> list[OAuthProvider]:
    """读取当前部署的 provider 列表；配置非法时 fail closed。"""
    providers: list[OAuthProvider] = []
    seen: set[str] = set()
    for item in _provider_payloads():
        try:
            provider = OAuthProvider.model_validate(item)
        except Exception as exc:
            raise OAuthProviderConfigError("OAuth provider 配置字段不合法") from exc
        if provider.code in seen:
            raise OAuthProviderConfigError(f"OAuth provider code 重复：{provider.code}")
        seen.add(provider.code)
        providers.append(provider)
    return providers


def provider_by_code(code: str) -> OAuthProvider:
    for provider in configured_providers():
        if provider.code == code:
            return provider
    raise OAuthProviderConfigError("未配置该 OAuth provider")


def merge_url_query(url: str, params: dict[str, str]) -> str:
    """在保留 provider 原 query 的前提下合并参数；同键以 params 为准。"""
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(params)
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def read_path(payload: Any, path: str | None) -> Any:
    """读取点路径；数组索引不支持，够用于常见 userinfo。"""
    if not path:
        return payload
    current = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def string_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
