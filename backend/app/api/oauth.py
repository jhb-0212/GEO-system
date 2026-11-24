"""平台 OAuth 授权接口：发起授权、回调、连接列表、刷新与撤销。

只有 `publish.read` 能查看连接；发起/刷新/撤销要 `publish.execute`。
回调不要求 Bearer 令牌，安全性由一次性 state + PKCE 绑定发起人和项目。
"""

from __future__ import annotations

import uuid
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    Envelope,
    OAuthAuthorizeData,
    OAuthConnectionData,
    OAuthProviderData,
    ok,
)
from app.core.config import settings
from app.core.errors import AppError, ProjectAccessError, ServiceUnavailableError
from app.core.secrets_box import decrypt_secret
from app.db.session import get_db
from app.services.queries import fetch_many
from app.models import Channel, OAuthConnection
from app.schemas import OAuthAuthorizeRequest
from app.services.audit import record_audit
from app.services.oauth import (
    OAuthProviderError,
    claim_state,
    connect_account,
    connection_data,
    create_authorization,
    exchange_code,
    fetch_userinfo,
    refresh_connection,
    revoke_connection,
)
from app.services.oauth_providers import OAuthProviderConfigError, configured_providers, provider_by_code
from app.services.project_scope import require_scoped_row

router = APIRouter(prefix="/api/v1", tags=["平台OAuth"], responses=COMMON_ERRORS)

DEFAULT_RETURN_PATH = "/workbench?section=publishing"


def _frontend_redirect(return_path: str | None, params: dict[str, str]) -> str:
    path = return_path or DEFAULT_RETURN_PATH
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        path = DEFAULT_RETURN_PATH
    base = settings.oauth_frontend_base_url.rstrip("/")
    target = urlparse(f"{base}{path}")
    query = parse_qsl(target.query, keep_blank_values=True)
    query.extend(params.items())
    return urlunparse(target._replace(query=urlencode(query, doseq=True)))


def _providers_or_503() -> list:
    try:
        return configured_providers()
    except OAuthProviderConfigError as exc:
        raise ServiceUnavailableError("平台 OAuth 配置不可用", code="oauth_provider_config_invalid") from exc


@router.get(
    "/projects/{project_id}/oauth/providers",
    response_model=Envelope[list[OAuthProviderData]],
)
def list_providers(
    ctx: ProjectContext = Depends(require_permission("publish.read")),
) -> dict:
    providers = _providers_or_503()
    return ok([{"code": item.code, "name": item.name, "scopes": item.scopes} for item in providers])


@router.post(
    "/projects/{project_id}/oauth/authorize",
    response_model=Envelope[OAuthAuthorizeData],
)
def start_authorization(
    payload: OAuthAuthorizeRequest,
    ctx: ProjectContext = Depends(require_permission("publish.execute")),
    db: Session = Depends(get_db),
) -> dict:
    try:
        provider = provider_by_code(payload.provider_code)
    except OAuthProviderConfigError as exc:
        raise AppError("未配置该平台授权", code="oauth_provider_not_configured") from exc

    channel = None
    if payload.channel_id is not None:
        channel = require_scoped_row(
            db, Channel, ctx.project.id, resource="channel", id=payload.channel_id
        )
        if not channel.is_active:
            raise AppError("渠道已停用，不能发起平台授权", code="oauth_channel_inactive")

    authorization_url, state, expires_at = create_authorization(
        db,
        project_id=ctx.project.id,
        provider=provider,
        channel_id=channel.id if channel else None,
        return_path=payload.return_path or DEFAULT_RETURN_PATH,
        actor_id=ctx.user.id,
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="oauth.authorize_started",
        target_type="oauth_provider",
        payload={
            "provider": provider.code,
            "channel_id": str(channel.id) if channel else None,
        },
    )
    db.commit()
    return ok(
        {
            "authorization_url": authorization_url,
            "state": state,
            "expires_at": expires_at,
        }
    )


@router.get(
    "/projects/{project_id}/oauth/connections",
    response_model=Envelope[list[OAuthConnectionData]],
)
def list_connections(
    ctx: ProjectContext = Depends(require_permission("publish.read")),
    db: Session = Depends(get_db),
) -> dict:
    rows = fetch_many(
        db,
        OAuthConnection,
        [OAuthConnection.project_id == ctx.project.id],
        order_by=(OAuthConnection.created_at.desc(), OAuthConnection.id),
    )
    return ok([connection_data(row) for row in rows])


@router.post(
    "/projects/{project_id}/oauth/connections/{connection_id}/refresh",
    response_model=Envelope[OAuthConnectionData],
)
def refresh(
    connection_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("publish.execute")),
    db: Session = Depends(get_db),
) -> dict:
    connection = require_scoped_row(
        db,
        OAuthConnection,
        ctx.project.id,
        resource="oauth_connection",
        id=connection_id,
        for_update=True,
    )
    try:
        connection = refresh_connection(db, connection=connection, actor_id=ctx.user.id)
    except OAuthProviderError as exc:
        raise AppError(str(exc), code=exc.code) from exc
    return ok(connection_data(connection))


@router.post(
    "/projects/{project_id}/oauth/connections/{connection_id}/revoke",
    response_model=Envelope[OAuthConnectionData],
)
def revoke(
    connection_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("publish.execute")),
    db: Session = Depends(get_db),
) -> dict:
    connection = require_scoped_row(
        db,
        OAuthConnection,
        ctx.project.id,
        resource="oauth_connection",
        id=connection_id,
        for_update=True,
    )
    connection = revoke_connection(db, connection=connection, actor_id=ctx.user.id)
    return ok(connection_data(connection))


@router.get("/oauth/callback/{provider_code}")
def oauth_callback(
    provider_code: str,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """平台回调：消费 state、兑换 token、绑定账号，最后 302 回工作台。"""
    if not code or not state:
        return RedirectResponse(
            _frontend_redirect(None, {"oauth": "error", "oauth_error": "oauth_code_missing"}),
            status_code=302,
        )

    try:
        provider = provider_by_code(provider_code)
    except OAuthProviderConfigError:
        return RedirectResponse(
            _frontend_redirect(None, {"oauth": "error", "oauth_error": "oauth_provider_not_configured"}),
            status_code=302,
        )

    try:
        state_row = claim_state(db, raw_state=state, provider_code=provider.code)
    except OAuthProviderError as exc:
        return RedirectResponse(
            _frontend_redirect(None, {"oauth": "error", "oauth_error": exc.code}),
            status_code=302,
        )

    return_path = state_row.return_path
    try:
        verifier = decrypt_secret(state_row.code_verifier_encrypted)
        if not verifier:
            raise OAuthProviderError("PKCE verifier 不可用", code="oauth_state_invalid")
        token_payload = exchange_code(
            provider,
            code=code,
            redirect_uri=state_row.redirect_uri,
            code_verifier=verifier,
        )
        userinfo = fetch_userinfo(provider, token_payload=token_payload)
        connection = connect_account(
            db,
            project_id=state_row.project_id,
            provider=provider,
            token_payload=token_payload,
            userinfo=userinfo,
            channel_id=state_row.channel_id,
            actor_id=state_row.created_by,
        )
        db.commit()
    except OAuthProviderError as exc:
        db.rollback()
        record_audit(
            db,
            project_id=state_row.project_id,
            actor_id=state_row.created_by,
            action="oauth.authorize_failed",
            target_type="oauth_provider",
            payload={"provider": provider.code, "error": exc.code},
        )
        db.commit()
        return RedirectResponse(
            _frontend_redirect(return_path, {"oauth": "error", "oauth_error": exc.code}),
            status_code=302,
        )
    except ProjectAccessError:
        db.rollback()
        return RedirectResponse(
            _frontend_redirect(return_path, {"oauth": "error", "oauth_error": "oauth_project_forbidden"}),
            status_code=302,
        )
    except Exception:
        db.rollback()
        return RedirectResponse(
            _frontend_redirect(return_path, {"oauth": "error", "oauth_error": "oauth_connection_failed"}),
            status_code=302,
        )

    return RedirectResponse(
        _frontend_redirect(
            return_path,
            {
                "oauth": "connected",
                "provider": provider.code,
                "connection_id": str(connection.id),
            },
        ),
        status_code=302,
    )
