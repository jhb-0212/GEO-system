"""只读 API 与 MCP：用项目级 API Key 鉴权，不暴露原始回答与写入动作。

REST 前缀 `/api/v1/read`；MCP 走 `/api/v1/mcp` 的 JSON-RPC（initialize / tools/list /
tools/call），四个只读工具与 REST 共用同一套 scope 校验。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, ok, ok_page
from app.core.errors import AppError
from app.db.session import get_db
from app.models import ApiKey
from app.schemas import ApiKeyCreate, McpRequest
from app.services import api_keys, readonly_api
from app.services.audit import record_audit

router = APIRouter(tags=["只读 API"], responses=COMMON_ERRORS)


def _key(db: Session, raw: str | None, scope: str) -> ApiKey:
    if not raw:
        raise AppError("缺少 X-API-Key", code="api_key_missing")
    return api_keys.authenticate(db, raw, required_scope=scope)


@router.get("/api/v1/read/overview")
def read_overview(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> dict:
    key = _key(db, x_api_key, "read:overview")
    db.commit()
    return ok(readonly_api.overview(db, key.project_id))


@router.get("/api/v1/read/questions")
def read_questions(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict:
    key = _key(db, x_api_key, "read:questions")
    rows = readonly_api.questions(db, key.project_id)
    db.commit()
    start = (page - 1) * page_size
    return ok_page(rows[start:start + page_size], page=page, page_size=page_size, total=len(rows))


@router.get("/api/v1/read/samples")
def read_samples(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    key = _key(db, x_api_key, "read:monitoring")
    rows = readonly_api.samples(db, key.project_id, limit)
    db.commit()
    return ok(rows)


@router.get("/api/v1/read/opportunities")
def read_opportunities(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    key = _key(db, x_api_key, "read:opportunities")
    rows = readonly_api.opportunities(db, key.project_id, limit)
    db.commit()
    return ok(rows)


MCP_TOOLS = [
    {
        "name": "geo_get_overview", "scope": "read:overview",
        "description": "获取项目 GEO 总览：提及率、引用率、被推荐率、Top3、答案份额（返回分子分母）。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "geo_list_questions", "scope": "read:questions",
        "description": "列出项目问题与当前版本号。",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 200}}, "additionalProperties": False},
    },
    {
        "name": "geo_list_samples", "scope": "read:monitoring",
        "description": "列出最近监测样本的品牌提及、推荐与排名；不含原始回答全文。",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 200}}, "additionalProperties": False},
    },
    {
        "name": "geo_list_opportunities", "scope": "read:opportunities",
        "description": "列出按优先级排序的机会。",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 200}}, "additionalProperties": False},
    },
]


def _mcp_result(request_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _mcp_error(request_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


@router.post("/api/v1/mcp")
def mcp(
    body: McpRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> dict:
    request_id = body.id
    if body.method == "initialize":
        return _mcp_result(request_id, {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "geo-readonly-mcp", "version": "1.0.0"},
        })
    if body.method == "notifications/initialized":
        return _mcp_result(request_id, {})
    if body.method == "tools/list":
        return _mcp_result(request_id, {"tools": [
            {k: v for k, v in tool.items() if k != "scope"} for tool in MCP_TOOLS
        ]})
    if body.method == "tools/call":
        name = str(body.params.get("name") or "")
        arguments = body.params.get("arguments") or {}
        tool = next((item for item in MCP_TOOLS if item["name"] == name), None)
        if tool is None:
            return _mcp_error(request_id, -32602, "未知工具")
        try:
            key = _key(db, x_api_key, tool["scope"])
            limit = min(int(arguments.get("limit", 50)), 200)
            if name == "geo_get_overview":
                payload = readonly_api.overview(db, key.project_id)
            elif name == "geo_list_questions":
                payload = readonly_api.questions(db, key.project_id)[:limit]
            elif name == "geo_list_samples":
                payload = readonly_api.samples(db, key.project_id, limit)
            else:
                payload = readonly_api.opportunities(db, key.project_id, limit)
            db.commit()
        except Exception as exc:  # noqa: BLE001 - MCP 需把业务错误转为 JSON-RPC error
            return _mcp_error(request_id, -32000, str(exc))
        return _mcp_result(request_id, {"content": [{"type": "text", "text": __import__("json").dumps(payload, ensure_ascii=False, default=str)}], "isError": False})
    return _mcp_error(request_id, -32601, "不支持的方法")




# ---------- 项目内 API Key 管理（登录态） ----------

manage_router = APIRouter(
    prefix="/api/v1/projects/{project_id}/api-keys",
    tags=["只读 API Key"],
    responses=COMMON_ERRORS,
)


@manage_router.get("")
def list_keys(
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    return ok(readonly_api.list_keys(db, ctx.project.id))


@manage_router.post("")
def create_key(
    body: ApiKeyCreate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    row, raw = api_keys.create_api_key(
        db, ctx.project.id, name=body.name, scopes=list(body.scopes),
        rate_limit_per_minute=body.rate_limit_per_minute, created_by=ctx.user.id,
        expires_at=body.expires_at,
    )
    record_audit(
        db, project_id=ctx.project.id, actor_id=ctx.user.id,
        action="api_key.create", target_type="api_key", target_id=row.id,
        payload={"scopes": row.scopes, "rate_limit_per_minute": row.rate_limit_per_minute},
    )
    db.commit()
    return ok({**api_keys.key_payload(row), "key": raw, "note": "明文只返回这一次"})


@manage_router.delete("/{key_id}")
def revoke_key(
    key_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    row = readonly_api.find_key(db, ctx.project.id, key_id)
    if row is None:
        raise AppError("API Key 不存在", code="api_key_missing")
    api_keys.revoke_api_key(db, row)
    record_audit(
        db, project_id=ctx.project.id, actor_id=ctx.user.id,
        action="api_key.revoke", target_type="api_key", target_id=row.id, payload={},
    )
    db.commit()
    return ok(api_keys.key_payload(row))



