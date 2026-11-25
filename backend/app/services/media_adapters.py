"""媒体渠道适配器与订单。

统一五个动作：list_inventory / quote / order / publish / status。
generic_http 约定供应商提供 JSON 接口，POST body 带 action；凭据从 token_env 指向的
环境变量读取，数据库不存明文。manual 不伪造成功：报价直接返回配置单价，订单停在
draft，等运营用 `manual_status` 回填。
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import MediaOrder, MediaProvider
from app.models.enums import MediaOrderStatus, MediaProviderAdapter
from app.services.state_machine import ensure_media_order_transition

logger = logging.getLogger(__name__)


def _request(provider: MediaProvider, payload: dict[str, Any]) -> dict[str, Any]:
    if not provider.endpoint:
        raise AppError("供应商未配置接口地址", code="media_provider_endpoint_missing")
    token = os.getenv(provider.token_env) if provider.token_env else None
    if provider.token_env and not token:
        raise AppError("供应商凭据环境变量未设置", code="media_provider_token_missing")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        provider.endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - 供应商地址由运营配置
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        raise AppError(f"供应商返回 HTTP {exc.code}", code="media_provider_http_error") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AppError(f"供应商接口不可用：{exc}", code="media_provider_unavailable") from exc


def _inventory_items(provider: MediaProvider, response: dict[str, Any]) -> list[dict[str, Any]]:
    raw = response.get("items") or response.get("inventory") or []
    items: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        price = item.get("price", item.get("unit_price"))
        items.append({
            "media_name": str(item.get("name") or item.get("media_name") or ""),
            "category": item.get("category"),
            "unit_price": float(price) if price not in (None, "") else None,
            "currency": item.get("currency", "CNY"),
            "lead_time_days": item.get("lead_time_days"),
            "note": item.get("note"),
        })
    return [item for item in items if item["media_name"]]


def list_inventory(provider: MediaProvider, *, query: str | None = None) -> dict[str, Any]:
    if provider.adapter == MediaProviderAdapter.MANUAL:
        configured = provider.config.get("inventory") if provider.config else None
        return {"items": _inventory_items(provider, {"items": configured or []}), "adapter": "manual"}
    return {"items": _inventory_items(provider, _request(provider, {"action": "list_inventory", "query": query})), "adapter": "generic_http"}


def quote(provider: MediaProvider, *, media_name: str, quantity: int = 1) -> dict[str, Any]:
    if not media_name.strip():
        raise AppError("媒体名称不能为空", code="media_name_required")
    if provider.adapter == MediaProviderAdapter.MANUAL:
        price = (provider.config or {}).get("unit_price")
        if price is None:
            raise AppError("人工供应商未配置单价，请运营补充报价", code="media_quote_manual_price_missing")
        return {"media_name": media_name, "quantity": quantity, "unit_price": float(price), "currency": (provider.config or {}).get("currency", "CNY"), "adapter": "manual", "note": "人工渠道：报价需运营书面确认"}
    response = _request(provider, {"action": "quote", "media_name": media_name, "quantity": quantity})
    price = response.get("unit_price", response.get("price"))
    if price is None:
        raise AppError("供应商未返回报价", code="media_quote_missing")
    return {
        "media_name": media_name, "quantity": quantity, "unit_price": float(price),
        "currency": response.get("currency", "CNY"), "lead_time_days": response.get("lead_time_days"),
        "quote_id": response.get("quote_id"), "adapter": "generic_http",
    }


def create_order(
    db: Session, provider: MediaProvider, *, idempotency_key: str, media_name: str,
    quantity: int = 1, unit_price: float | None = None, created_by=None,
) -> tuple[MediaOrder, bool]:
    existing = db.scalar(select(MediaOrder).where(
        MediaOrder.project_id == provider.project_id,
        MediaOrder.provider_id == provider.id,
        MediaOrder.idempotency_key == idempotency_key,
    ))
    if existing:
        return existing, False
    order = MediaOrder(
        project_id=provider.project_id, provider_id=provider.id,
        idempotency_key=idempotency_key, media_name=media_name, quantity=quantity,
        unit_price=Decimal(str(unit_price)) if unit_price is not None else None,
        currency=(provider.config or {}).get("currency", "CNY"),
        status=MediaOrderStatus.DRAFT,
        request_payload={"media_name": media_name, "quantity": quantity, "unit_price": unit_price},
        created_by=created_by,
    )
    db.add(order)
    db.flush()
    if provider.adapter == MediaProviderAdapter.MANUAL:
        order.response_payload = {"adapter": "manual", "note": "等待运营向供应商下单后回填"}
        db.flush()
        return order, True
    try:
        response = _request(provider, {
            "action": "order", "idempotency_key": idempotency_key,
            "media_name": media_name, "quantity": quantity, "unit_price": unit_price,
        })
    except AppError as exc:
        order.status = ensure_media_order_transition(order.status, MediaOrderStatus.FAILED)
        order.error = str(exc)
        db.flush()
        return order, True
    order.external_order_id = str(response.get("order_id") or response.get("id") or "") or None
    order.response_payload = response
    order.status = ensure_media_order_transition(
        order.status,
        MediaOrderStatus.SUBMITTED if order.external_order_id else MediaOrderStatus.FAILED,
    )
    order.submitted_at = datetime.now(timezone.utc) if order.status == MediaOrderStatus.SUBMITTED else None
    if order.status == MediaOrderStatus.FAILED:
        order.error = "供应商未返回订单号"
    db.flush()
    return order, True


def publish_order(db: Session, order: MediaOrder, provider: MediaProvider, *, publish_url: str | None = None) -> MediaOrder:
    if provider.adapter == MediaProviderAdapter.MANUAL:
        if order.status not in (MediaOrderStatus.CONFIRMED, MediaOrderStatus.DRAFT):
            raise AppError("人工订单需先确认才能回填发布", code="media_order_not_confirmable")
        if not publish_url:
            raise AppError("人工渠道发布必须填写发布链接", code="media_publish_url_required")
        order.status = ensure_media_order_transition(order.status, MediaOrderStatus.PUBLISHED)
        order.publish_url = publish_url
        order.published_at = datetime.now(timezone.utc)
        db.flush()
        return order
    response = _request(provider, {"action": "publish", "order_id": order.external_order_id})
    order.response_payload = response
    order.publish_url = response.get("publish_url") or publish_url
    order.status = ensure_media_order_transition(
        order.status,
        MediaOrderStatus.PUBLISHED
        if response.get("publish_url") or publish_url
        else MediaOrderStatus.SUBMITTED,
    )
    if order.status == MediaOrderStatus.PUBLISHED:
        order.published_at = datetime.now(timezone.utc)
    db.flush()
    return order


def sync_status(db: Session, order: MediaOrder, provider: MediaProvider) -> MediaOrder:
    if provider.adapter == MediaProviderAdapter.MANUAL:
        return order
    response = _request(provider, {"action": "status", "order_id": order.external_order_id})
    mapped = str(response.get("status") or "").lower()
    if mapped in {status.value for status in MediaOrderStatus}:
        order.status = ensure_media_order_transition(order.status, MediaOrderStatus(mapped))
    order.response_payload = response
    order.publish_url = response.get("publish_url") or order.publish_url
    if order.status == MediaOrderStatus.PUBLISHED and order.published_at is None:
        order.published_at = datetime.now(timezone.utc)
    db.flush()
    return order


def manual_status(
    db: Session, order: MediaOrder, *, status: MediaOrderStatus, external_order_id: str | None = None,
    publish_url: str | None = None, note: str | None = None,
) -> MediaOrder:
    if order.status == MediaOrderStatus.PUBLISHED and status != MediaOrderStatus.PUBLISHED:
        raise AppError("已发布订单不能回退状态", code="media_order_published_immutable")
    order.status = ensure_media_order_transition(order.status, status)
    if external_order_id:
        order.external_order_id = external_order_id
    if publish_url:
        order.publish_url = publish_url
    if status == MediaOrderStatus.PUBLISHED:
        order.published_at = datetime.now(timezone.utc)
    order.response_payload = {**(order.response_payload or {}), "manual_note": note, "manual_at": datetime.now(timezone.utc).isoformat()}
    db.flush()
    return order


def provider_by_code(db: Session, project_id, code: str) -> MediaProvider | None:
    return db.scalar(select(MediaProvider).where(
        MediaProvider.project_id == project_id, MediaProvider.code == code
    ))


def get_provider(db: Session, project_id, provider_id) -> MediaProvider:
    provider = db.scalar(select(MediaProvider).where(
        MediaProvider.id == provider_id, MediaProvider.project_id == project_id
    ))
    if provider is None:
        raise AppError("媒体供应商不存在", code="media_provider_missing")
    return provider


def get_order(db: Session, project_id, order_id) -> MediaOrder:
    order = db.scalar(select(MediaOrder).where(
        MediaOrder.id == order_id, MediaOrder.project_id == project_id
    ))
    if order is None:
        raise AppError("媒体订单不存在", code="media_order_missing")
    return order


def list_providers(db: Session, project_id) -> list[dict]:
    rows = db.scalars(select(MediaProvider).where(
        MediaProvider.project_id == project_id
    ).order_by(MediaProvider.created_at)).all()
    return [provider_payload(row) for row in rows]


def list_orders(db: Session, project_id, *, status=None, page: int = 1, page_size: int = 20) -> tuple[list[dict], int]:
    filters = [MediaOrder.project_id == project_id]
    if status is not None:
        filters.append(MediaOrder.status == status)
    rows = db.scalars(select(MediaOrder).where(*filters).order_by(
        MediaOrder.created_at.desc()
    ).offset((page - 1) * page_size).limit(page_size)).all()
    total = db.query(MediaOrder).filter(*filters).count()
    return [order_payload(row) for row in rows], total


def provider_payload(provider: MediaProvider) -> dict[str, Any]:
    return {
        "id": str(provider.id), "code": provider.code, "name": provider.name,
        "adapter": provider.adapter.value, "endpoint": provider.endpoint,
        "token_env": provider.token_env, "config": provider.config,
        "capabilities": provider.capabilities, "is_active": provider.is_active,
        "last_health": provider.last_health,
        "last_checked_at": provider.last_checked_at.isoformat() if provider.last_checked_at else None,
    }


def order_payload(order: MediaOrder) -> dict[str, Any]:
    return {
        "id": str(order.id), "provider_id": str(order.provider_id),
        "idempotency_key": order.idempotency_key, "external_order_id": order.external_order_id,
        "media_name": order.media_name, "quantity": order.quantity,
        "unit_price": float(order.unit_price) if order.unit_price is not None else None,
        "currency": order.currency, "status": order.status.value,
        "request_payload": order.request_payload, "response_payload": order.response_payload,
        "error": order.error, "publish_url": order.publish_url,
        "submitted_at": order.submitted_at.isoformat() if order.submitted_at else None,
        "published_at": order.published_at.isoformat() if order.published_at else None,
    }
