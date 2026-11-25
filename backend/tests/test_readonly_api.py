"""只读 API Key：明文只返回一次、scope 隔离、撤销、MCP 四工具。"""

from __future__ import annotations

import uuid

from app.core.security import create_access_token
from app.models.enums import RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_api_key_scopes_revoke_and_mcp(client, project_factory, user_factory, member_factory):
    project = project_factory(f"api-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"api-editor-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)

    created = client.post(
        f"/api/v1/projects/{project.id}/api-keys",
        json={"name": "客户只读", "scopes": ["read:overview", "read:questions"], "rate_limit_per_minute": 30},
        headers=_auth(editor),
    )
    assert created.status_code == 200, created.text
    payload = created.json()["data"]
    raw = payload["key"]
    assert raw.startswith("geo_pk_") and payload["key_prefix"] in raw
    listed = client.get(f"/api/v1/projects/{project.id}/api-keys", headers=_auth(editor)).json()["data"]
    assert listed and all("key" not in item for item in listed)

    overview = client.get("/api/v1/read/overview", headers={"X-API-Key": raw})
    assert overview.status_code == 200, overview.text
    assert "brand_recommendation_rate" in overview.json()["data"]

    questions = client.get("/api/v1/read/questions", headers={"X-API-Key": raw})
    assert questions.status_code == 200, questions.text

    denied = client.get("/api/v1/read/samples", headers={"X-API-Key": raw})
    assert denied.status_code == 400
    assert denied.json()["error"]["code"] == "api_key_scope_denied"

    init = client.post("/api/v1/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert init.status_code == 200, init.text
    assert init.json()["result"]["serverInfo"]["name"] == "geo-readonly-mcp"

    tools = client.post("/api/v1/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {tool["name"] for tool in tools.json()["result"]["tools"]}
    assert names == {"geo_get_overview", "geo_list_questions", "geo_list_samples", "geo_list_opportunities"}

    call = client.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "geo_get_overview", "arguments": {}}},
        headers={"X-API-Key": raw},
    )
    assert call.status_code == 200, call.text
    assert call.json()["result"]["isError"] is False

    mcp_denied = client.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "geo_list_samples", "arguments": {}}},
        headers={"X-API-Key": raw},
    )
    assert mcp_denied.json()["error"]["code"] == -32000

    revoked = client.delete(f"/api/v1/projects/{project.id}/api-keys/{payload['id']}", headers=_auth(editor))
    assert revoked.status_code == 200, revoked.text
    after = client.get("/api/v1/read/overview", headers={"X-API-Key": raw})
    assert after.status_code == 400
    assert after.json()["error"]["code"] in {"api_key_invalid"}
