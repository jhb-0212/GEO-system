"""媒体渠道适配器接口入参。"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class MediaProviderCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    adapter: Literal["generic_http", "manual"] = "manual"
    endpoint: str | None = Field(default=None, max_length=500)
    token_env: str | None = Field(default=None, max_length=128)
    config: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[Literal["list_inventory", "quote", "order", "publish", "status"]] = Field(
        default_factory=lambda: ["quote", "order", "publish", "status"]
    )


class MediaProviderUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    endpoint: str | None = Field(default=None, max_length=500)
    token_env: str | None = Field(default=None, max_length=128)
    config: dict[str, Any] | None = None
    capabilities: list[str] | None = None
    is_active: bool | None = None


class MediaQuoteRequest(BaseModel):
    media_name: str = Field(min_length=1, max_length=200)
    quantity: int = Field(default=1, ge=1, le=100)


class MediaOrderCreate(BaseModel):
    idempotency_key: str = Field(min_length=4, max_length=120)
    media_name: str = Field(min_length=1, max_length=200)
    quantity: int = Field(default=1, ge=1, le=100)
    unit_price: float | None = Field(default=None, ge=0)


class MediaManualStatus(BaseModel):
    status: Literal["submitted", "confirmed", "published", "failed", "cancelled"]
    external_order_id: str | None = Field(default=None, max_length=128)
    publish_url: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=1000)
