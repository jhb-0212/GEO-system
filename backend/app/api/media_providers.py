"""媒体渠道适配器 API：供应商登记、库存/报价、下单、发布、状态同步。"""

import uuid

from fastapi import APIRouter, Depends, Query

from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, ok, ok_page
from app.core.errors import AppError
from app.db.session import get_db
from app.models import MediaProvider
from app.models.enums import MediaOrderStatus, MediaProviderAdapter
from app.schemas import MediaManualStatus, MediaOrderCreate, MediaProviderCreate, MediaProviderUpdate, MediaQuoteRequest
from app.services import media_adapters
from app.services.audit import record_audit

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/media-providers",
    tags=["媒体渠道适配器"],
    responses=COMMON_ERRORS,
)


@router.get("")
def list_providers(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
) -> dict:
    return ok(media_adapters.list_providers(db, ctx.project.id))


@router.post("")
def create_provider(
    body: MediaProviderCreate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    existing = media_adapters.provider_by_code(db, ctx.project.id, body.code)
    if existing is not None:
        raise AppError("供应商编码已存在", code="media_provider_code_duplicate")
    provider = MediaProvider(
        project_id=ctx.project.id, code=body.code, name=body.name,
        adapter=MediaProviderAdapter(body.adapter), endpoint=body.endpoint,
        token_env=body.token_env, config=body.config, capabilities=body.capabilities,
        is_active=True,
    )
    db.add(provider)
    db.flush()
    record_audit(
        db, project_id=ctx.project.id, actor_id=ctx.user.id,
        action="media_provider.create", target_type="media_provider", target_id=provider.id,
        payload={"code": body.code, "adapter": body.adapter},
    )
    db.commit()
    return ok(media_adapters.provider_payload(provider))


@router.patch("/{provider_id}")
def update_provider(
    provider_id: uuid.UUID, body: MediaProviderUpdate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    provider = media_adapters.get_provider(db, ctx.project.id, provider_id)
    for field in ("name", "endpoint", "token_env", "config", "capabilities", "is_active"):
        value = getattr(body, field)
        if value is not None:
            setattr(provider, field, value)
    db.flush()
    record_audit(
        db, project_id=ctx.project.id, actor_id=ctx.user.id,
        action="media_provider.update", target_type="media_provider", target_id=provider.id,
        payload=body.model_dump(exclude_none=True),
    )
    db.commit()
    return ok(media_adapters.provider_payload(provider))


@router.post("/{provider_id}/inventory")
def inventory(
    provider_id: uuid.UUID, query: str | None = Query(default=None, max_length=100),
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
) -> dict:
    provider = media_adapters.get_provider(db, ctx.project.id, provider_id)
    if "list_inventory" not in (provider.capabilities or []):
        raise AppError("该供应商未开通库存查询", code="media_capability_unsupported")
    return ok(media_adapters.list_inventory(provider, query=query))


@router.post("/{provider_id}/quote")
def request_quote(
    provider_id: uuid.UUID, body: MediaQuoteRequest,
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
) -> dict:
    provider = media_adapters.get_provider(db, ctx.project.id, provider_id)
    if "quote" not in (provider.capabilities or []):
        raise AppError("该供应商未开通报价", code="media_capability_unsupported")
    return ok(media_adapters.quote(provider, media_name=body.media_name, quantity=body.quantity))


@router.post("/{provider_id}/orders")
def create_order(
    provider_id: uuid.UUID, body: MediaOrderCreate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    provider = media_adapters.get_provider(db, ctx.project.id, provider_id)
    if "order" not in (provider.capabilities or []):
        raise AppError("该供应商未开通下单", code="media_capability_unsupported")
    order, created = media_adapters.create_order(
        db, provider, idempotency_key=body.idempotency_key, media_name=body.media_name,
        quantity=body.quantity, unit_price=body.unit_price, created_by=ctx.user.id,
    )
    record_audit(
        db, project_id=ctx.project.id, actor_id=ctx.user.id,
        action="media_order.create", target_type="media_order", target_id=order.id,
        payload={"idempotency_key": body.idempotency_key, "created": created, "status": order.status.value},
    )
    db.commit()
    return ok({**media_adapters.order_payload(order), "created": created})


@router.get("/orders")
def list_orders(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    status: MediaOrderStatus | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    rows, total = media_adapters.list_orders(
        db, ctx.project.id, status=status, page=page, page_size=page_size,
    )
    return ok_page(rows, page=page, page_size=page_size, total=total)


@router.post("/orders/{order_id}/publish")
def publish_order(
    order_id: uuid.UUID, publish_url: str | None = Query(default=None, max_length=500),
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    order = media_adapters.get_order(db, ctx.project.id, order_id)
    provider = media_adapters.get_provider(db, ctx.project.id, order.provider_id)
    order = media_adapters.publish_order(db, order, provider, publish_url=publish_url)
    record_audit(
        db, project_id=ctx.project.id, actor_id=ctx.user.id,
        action="media_order.publish", target_type="media_order", target_id=order.id,
        payload={"publish_url": order.publish_url, "status": order.status.value},
    )
    db.commit()
    return ok(media_adapters.order_payload(order))


@router.post("/orders/{order_id}/sync")
def sync_order(
    order_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
) -> dict:
    order = media_adapters.get_order(db, ctx.project.id, order_id)
    provider = media_adapters.get_provider(db, ctx.project.id, order.provider_id)
    order = media_adapters.sync_status(db, order, provider)
    db.commit()
    return ok(media_adapters.order_payload(order))


@router.post("/orders/{order_id}/manual-status")
def manual_status(
    order_id: uuid.UUID, body: MediaManualStatus,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    order = media_adapters.get_order(db, ctx.project.id, order_id)
    order = media_adapters.manual_status(
        db, order, status=MediaOrderStatus(body.status), external_order_id=body.external_order_id,
        publish_url=body.publish_url, note=body.note,
    )
    record_audit(
        db, project_id=ctx.project.id, actor_id=ctx.user.id,
        action="media_order.manual_status", target_type="media_order", target_id=order.id,
        payload={"status": order.status.value, "note": body.note},
    )
    db.commit()
    return ok(media_adapters.order_payload(order))

