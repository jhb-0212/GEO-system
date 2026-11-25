"""只读 API Key 与 MCP 入参。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ReadScope = Literal["read:overview", "read:questions", "read:monitoring", "read:opportunities"]


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    scopes: list[ReadScope] = Field(min_length=1)
    rate_limit_per_minute: int = Field(default=60, ge=1, le=600)
    expires_at: datetime | None = None


class McpRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
