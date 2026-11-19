"""通用 OAuth2 授权码流程。

边界：
- 授权 state 只存 SHA-256，回调消费一次即作废；PKCE verifier 加密落库。
- access_token / refresh_token 只存加密密文；任何 API 响应都不返回令牌。
- 回调成功后只把 connection_id 带回前端，不在 URL 中带令牌。
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.secrets_box import decrypt_secret, encrypt_secret
from app.models import Channel, OAuthAuthorizationState, OAuthConnection
from app.models.enums import OAuthConnectionStatus
from app.services.audit import record_audit
from app.services.oauth_providers import (
    OAuthProvider,
    OAuthProviderConfigError,
    merge_url_query,
    provider_by_code,
    read_path,
    string_value,
)


class OAuthProviderError(RuntimeError):
    """平台交换/刷新/撤销失败：对外只给稳定错误码，不转发平台响应正文。"""

    def __init__(self, message: str, *, code: str = "oauth_provider_error") -> None:
        super().__init__(message)
        self.code = code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _callback_url(provider_code: str) -> str:
    base = (settings.oauth_callback_base_url or settings.api_base_url).rstrip("/")
    return f"{base}/api/v1/oauth/callback/{quote(provider_code, safe='')}"


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _token_auth(provider: OAuthProvider, data: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    headers = {"Accept": "application/json"}
    if provider.token_auth_method == "client_secret_basic":
        encoded = base64.b64encode(
            f"{provider.client_id}:{provider.client_secret}".encode("utf-8")
        ).decode("ascii")
        headers["Authorization"] = f"Basic {encoded}"
    else:
        data["client_id"] = provider.client_id
        data["client_secret"] = provider.client_secret
    return headers, data


def _http_json(
    method: str,
    url: str,
    *,
    data: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=settings.oauth_http_timeout_seconds, follow_redirects=False) as client:
            response = client.request(method, url, data=data, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OAuthProviderError("平台授权服务请求失败", code="oauth_provider_unavailable") from exc
    if not isinstance(payload, dict):
        raise OAuthProviderError("平台授权响应格式不正确", code="oauth_provider_bad_response")
    return payload


def _http_empty_or_json(
    method: str,
    url: str,
    *,
    data: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> None:
    """撤销端点常返回 200 空 body，只认状态码。"""
    try:
        with httpx.Client(timeout=settings.oauth_http_timeout_seconds, follow_redirects=False) as client:
            response = client.request(method, url, data=data, headers=headers)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise OAuthProviderError("平台撤销请求失败", code="oauth_provider_unavailable") from exc


def create_authorization(
    db: Session,
    *,
    project_id: uuid.UUID,
    provider: OAuthProvider,
    channel_id: uuid.UUID | None,
    return_path: str,
    actor_id: uuid.UUID | None,
) -> tuple[str, str, datetime]:
    """生成一次性 state + PKCE，返回 (authorization_url, raw_state, expires_at)。"""
    raw_state = secrets.token_urlsafe(32)
    state_hash = hashlib.sha256(raw_state.encode("utf-8")).hexdigest()
    code_verifier = secrets.token_urlsafe(64)
    redirect_uri = _callback_url(provider.code)
    expires_at = _now() + timedelta(minutes=max(1, settings.oauth_state_expire_minutes))

    db.add(
        OAuthAuthorizationState(
            project_id=project_id,
            provider_code=provider.code,
            channel_id=channel_id,
            state_hash=state_hash,
            code_verifier_encrypted=encrypt_secret(code_verifier),
            redirect_uri=redirect_uri,
            return_path=return_path,
            created_by=actor_id,
            expires_at=expires_at,
        )
    )
    db.flush()

    params = {
        "response_type": "code",
        "client_id": provider.client_id,
        "redirect_uri": redirect_uri,
        "state": raw_state,
        "code_challenge": _pkce_challenge(code_verifier),
        "code_challenge_method": "S256",
    }
    if provider.scopes:
        params["scope"] = " ".join(provider.scopes)
    # 显式参数放最后，部署方的额外参数不能覆盖 state / redirect / PKCE
    merged = {**provider.authorization_params, **params}
    return merge_url_query(provider.authorize_url, merged), raw_state, expires_at


def claim_state(db: Session, *, raw_state: str, provider_code: str) -> OAuthAuthorizationState:
    """按 state 摘要查一次性记录；有效则立刻消费并提交，防重放。"""
    state_hash = hashlib.sha256((raw_state or "").encode("utf-8")).hexdigest()
    row = db.scalar(
        select(OAuthAuthorizationState)
        .where(
            OAuthAuthorizationState.state_hash == state_hash,
            OAuthAuthorizationState.provider_code == provider_code,
        )
        .with_for_update()
    )
    if row is None or row.consumed_at is not None:
        raise OAuthProviderError("授权 state 无效或已使用", code="oauth_state_invalid")
    if row.expires_at <= _now():
        raise OAuthProviderError("授权 state 已过期", code="oauth_state_expired")
    row.consumed_at = _now()
    db.commit()
    return row


def exchange_code(
    provider: OAuthProvider,
    *,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict[str, Any]:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
        **provider.token_params,
    }
    headers, body = _token_auth(provider, data)
    payload = _http_json("POST", provider.token_url, data=body, headers=headers)
    token_payload = read_path(payload, provider.token_response_path)
    if not isinstance(token_payload, dict):
        raise OAuthProviderError("平台令牌响应缺少字段", code="oauth_token_response_invalid")
    access_token = string_value(token_payload.get("access_token"))
    if not access_token:
        raise OAuthProviderError("平台没有返回 access_token", code="oauth_token_missing")
    return {**token_payload, "access_token": access_token}


def fetch_userinfo(
    provider: OAuthProvider,
    *,
    token_payload: dict[str, Any],
) -> dict[str, str | None]:
    access_token = string_value(token_payload.get("access_token")) or ""
    headers = {"Accept": "application/json"}
    params: dict[str, str] = {}
    data: dict[str, str] = {}
    if provider.userinfo_auth == "bearer":
        headers["Authorization"] = f"Bearer {access_token}"
    elif provider.userinfo_method == "GET":
        params["access_token"] = access_token
    else:
        data["access_token"] = access_token
    for param_name, token_field in provider.userinfo_params.items():
        value = string_value(token_payload.get(token_field))
        if value:
            (params if provider.userinfo_method == "GET" else data)[param_name] = value

    method = provider.userinfo_method
    payload = _http_json(
        method,
        provider.userinfo_url,
        data=data if method == "POST" else None,
        params=params if method == "GET" else None,
        headers=headers,
    )
    info = read_path(payload, provider.userinfo_response_path)
    if not isinstance(info, dict):
        raise OAuthProviderError("平台用户信息格式不正确", code="oauth_userinfo_invalid")

    user_id = string_value(read_path(info, provider.user_id_path))
    if not user_id:
        for fallback in ("sub", "id", "openid", "unionid", "user_id"):
            user_id = string_value(read_path(info, fallback))
            if user_id:
                break
    if not user_id:
        raise OAuthProviderError("平台用户信息缺少稳定账号标识", code="oauth_userinfo_missing_id")

    name = string_value(read_path(info, provider.user_name_path))
    for fallback in ("name", "display_name", "nickname", "username"):
        if name:
            break
        name = string_value(read_path(info, fallback))
    email = string_value(read_path(info, provider.user_email_path))
    return {"external_account_id": user_id, "external_account_name": name, "external_account_email": email}


def _scopes_from_token(provider: OAuthProvider, token_payload: dict[str, Any]) -> list[str]:
    raw_scope = token_payload.get("scope")
    if isinstance(raw_scope, str) and raw_scope.strip():
        return [item for item in raw_scope.split() if item]
    return list(provider.scopes)


def _expires_at(token_payload: dict[str, Any]) -> datetime | None:
    raw_value = token_payload.get("expires_in")
    try:
        seconds = int(raw_value) if raw_value is not None else 0
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return _now() + timedelta(seconds=seconds)


def _apply_tokens(
    connection: OAuthConnection,
    *,
    provider: OAuthProvider,
    token_payload: dict[str, Any],
    userinfo: dict[str, str | None] | None = None,
    channel_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> None:
    connection.access_token_encrypted = encrypt_secret(str(token_payload["access_token"]))
    refresh_token = string_value(token_payload.get("refresh_token"))
    if refresh_token:
        connection.refresh_token_encrypted = encrypt_secret(refresh_token)
    connection.token_type = string_value(token_payload.get("token_type")) or "Bearer"
    connection.expires_at = _expires_at(token_payload)
    connection.scopes = _scopes_from_token(provider, token_payload)
    connection.status = OAuthConnectionStatus.CONNECTED
    connection.revoked_at = None
    if connection.connected_by is None:
        connection.connected_by = actor_id
    if connection.connected_at is None:
        connection.connected_at = _now()
    if channel_id is not None:
        connection.channel_id = channel_id
    if userinfo:
        connection.external_account_name = userinfo.get("external_account_name")
        connection.external_account_email = userinfo.get("external_account_email")
    connection.metadata_json = {
        **(connection.metadata_json or {}),
        "provider": provider.code,
        "token_type": connection.token_type,
    }


def connect_account(
    db: Session,
    *,
    project_id: uuid.UUID,
    provider: OAuthProvider,
    token_payload: dict[str, Any],
    userinfo: dict[str, str | None],
    channel_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
) -> OAuthConnection:
    external_id = userinfo["external_account_id"]
    if not external_id:
        raise OAuthProviderError("平台账号标识为空", code="oauth_userinfo_missing_id")
    connection = db.scalar(
        select(OAuthConnection).where(
            OAuthConnection.project_id == project_id,
            OAuthConnection.provider_code == provider.code,
            OAuthConnection.external_account_id == external_id,
        )
    )
    created = connection is None
    if connection is None:
        connection = OAuthConnection(
            project_id=project_id,
            provider_code=provider.code,
            external_account_id=external_id,
        )
        db.add(connection)
        db.flush()
    _apply_tokens(
        connection,
        provider=provider,
        token_payload=token_payload,
        userinfo=userinfo,
        channel_id=channel_id,
        actor_id=actor_id,
    )
    record_audit(
        db,
        project_id=project_id,
        actor_id=actor_id,
        action="oauth.connection_created" if created else "oauth.connection_reconnected",
        target_type="oauth_connection",
        target_id=connection.id,
        payload={
            "provider": provider.code,
            "external_account_id": external_id,
            "channel_id": str(channel_id) if channel_id else None,
            "scopes": connection.scopes,
            "expires_at": connection.expires_at.isoformat() if connection.expires_at else None,
        },
    )
    db.flush()
    return connection


def refresh_connection(
    db: Session,
    *,
    connection: OAuthConnection,
    actor_id: uuid.UUID | None,
) -> OAuthConnection:
    provider = provider_by_code(connection.provider_code)
    if connection.status == OAuthConnectionStatus.REVOKED:
        raise OAuthProviderError("连接已撤销，请重新授权", code="oauth_connection_revoked")
    refresh_token = decrypt_secret(connection.refresh_token_encrypted)
    if not refresh_token:
        raise OAuthProviderError("该连接没有 refresh_token，请重新授权", code="oauth_refresh_token_missing")

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        **provider.token_params,
    }
    headers, body = _token_auth(provider, data)
    try:
        payload = _http_json("POST", provider.token_url, data=body, headers=headers)
        token_payload = read_path(payload, provider.token_response_path)
        if not isinstance(token_payload, dict):
            raise OAuthProviderError("平台刷新响应缺少字段", code="oauth_token_response_invalid")
        access_token = string_value(token_payload.get("access_token"))
        if not access_token:
            raise OAuthProviderError("平台没有返回新的 access_token", code="oauth_token_missing")
        _apply_tokens(
            connection,
            provider=provider,
            token_payload={**token_payload, "access_token": access_token},
            actor_id=actor_id,
        )
        connection.last_refreshed_at = _now()
    except OAuthProviderError:
        connection.status = OAuthConnectionStatus.ERROR
        db.commit()
        raise
    record_audit(
        db,
        project_id=connection.project_id,
        actor_id=actor_id,
        action="oauth.connection_refreshed",
        target_type="oauth_connection",
        target_id=connection.id,
        payload={
            "provider": provider.code,
            "expires_at": connection.expires_at.isoformat() if connection.expires_at else None,
        },
    )
    db.commit()
    return connection


def revoke_connection(
    db: Session,
    *,
    connection: OAuthConnection,
    actor_id: uuid.UUID | None,
) -> OAuthConnection:
    try:
        provider = provider_by_code(connection.provider_code)
    except OAuthProviderConfigError:
        provider = None
    access_token = decrypt_secret(connection.access_token_encrypted)
    remote_revoked = False
    remote_error = None
    if provider and provider.revoke_url and access_token:
        try:
            data = {"token": access_token, "token_type_hint": "access_token"}
            headers, body = _token_auth(provider, data)
            _http_empty_or_json("POST", provider.revoke_url, data=body, headers=headers)
            remote_revoked = True
        except OAuthProviderError as exc:
            remote_error = exc.code
    connection.access_token_encrypted = None
    connection.refresh_token_encrypted = None
    connection.expires_at = None
    connection.status = OAuthConnectionStatus.REVOKED
    connection.revoked_at = _now()
    connection.metadata_json = {
        **(connection.metadata_json or {}),
        "remote_revoked": remote_revoked,
        "remote_revoke_error": remote_error,
    }
    record_audit(
        db,
        project_id=connection.project_id,
        actor_id=actor_id,
        action="oauth.connection_revoked",
        target_type="oauth_connection",
        target_id=connection.id,
        payload={
            "provider": connection.provider_code,
            "external_account_id": connection.external_account_id,
            "remote_revoked": remote_revoked,
        },
    )
    db.commit()
    return connection


def connection_data(connection: OAuthConnection) -> dict[str, Any]:
    try:
        provider_name = provider_by_code(connection.provider_code).name
    except OAuthProviderConfigError:
        provider_name = connection.provider_code
    return {
        "id": str(connection.id),
        "provider_code": connection.provider_code,
        "provider_name": provider_name,
        "channel_id": str(connection.channel_id) if connection.channel_id else None,
        "external_account_id": connection.external_account_id,
        "external_account_name": connection.external_account_name,
        "external_account_email": connection.external_account_email,
        "scopes": connection.scopes,
        "status": connection.status.value,
        "has_refresh_token": bool(connection.refresh_token_encrypted),
        "expires_at": connection.expires_at,
        "connected_at": connection.connected_at,
        "last_refreshed_at": connection.last_refreshed_at,
        "revoked_at": connection.revoked_at,
    }
