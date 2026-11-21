"""AI 平台入口自助配置与连通性测试：只验证配置/协议，不触达真实平台。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models import AiEngine, AiEngineEntry, AuditLog
from app.models.enums import EngineEntryType, EngineProtocol, RoleCode
from app.services.engine_connectors import test_entry_connection as probe_entry_connection
from app.services.monitoring_collection import (
    AccessBlockedFailure,
    UnconfiguredAdapter,
    build_entry_adapter,
)
from app.services.openai_compatible_adapter import OpenAICompatibleAdapter


def auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _make_engine(db, *, code: str | None = None) -> AiEngine:
    row = AiEngine(
        code=code or f"eng-{uuid.uuid4().hex[:6]}",
        name="测试平台",
        vendor="测试厂商",
        supports_search=False,
        supports_citation=False,
        is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def _make_entry(
    db,
    engine: AiEngine,
    *,
    protocol: EngineProtocol = EngineProtocol.OPENAI_COMPATIBLE,
    entry_type: EngineEntryType = EngineEntryType.API,
    name: str = "测试入口",
    credential_ref: str | None = "DEEPSEEK_API_KEY",
    entry_url: str = "https://api.deepseek.com/v1",
) -> AiEngineEntry:
    row = AiEngineEntry(
        engine_id=engine.id,
        entry_type=entry_type,
        name=name,
        entry_url=entry_url,
        protocol=protocol,
        model_name="deepseek-chat",
        credential_ref=credential_ref,
        supports_search=False,
        is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def test_engine_manage_can_create_entry(client, db, user_factory, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    engine = _make_engine(db)
    sys_admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    response = client.post(
        f"/api/v1/engines/{engine.id}/entries",
        json={
            "entry_type": "api",
            "name": "DeepSeek 官方 API",
            "entry_url": "https://api.deepseek.com/v1",
            "protocol": "openai_compatible",
            "model_name": "deepseek-chat",
            "credential_ref": "DEEPSEEK_API_KEY",
            "supports_search": False,
        },
        headers=auth(sys_admin),
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["protocol"] == "openai_compatible"
    assert data["credential_ref"] == "DEEPSEEK_API_KEY"
    assert data["credential_configured"] is False
    assert "api_key" not in data
    assert "password" not in data


def test_create_yuanbao_search_entry(client, db, user_factory, monkeypatch):
    engine = _make_engine(db)
    sys_admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    monkeypatch.setenv("YUANBAO_SECRET_ID", "AKIDEXAMPLE")
    monkeypatch.setenv("YUANBAO_SECRET_KEY", "SECRETEXAMPLE")
    response = client.post(
        f"/api/v1/engines/{engine.id}/entries",
        json={
            "entry_type": "api",
            "name": "腾讯元宝 SearchPro",
            "entry_url": "https://wsa.tencentcloudapi.com",
            "protocol": "yuanbao_search",
            "model_name": "yuanbao-search",
            "credential_ref": "YUANBAO_SECRET_ID",
            "supports_search": True,
            "supports_citation": True,
        },
        headers=auth(sys_admin),
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["protocol"] == "yuanbao_search"
    assert data["credential_configured"] is True
    assert "SECRETEXAMPLE" not in response.text


def test_create_doubao_search_entry(client, db, user_factory, monkeypatch):
    engine = _make_engine(db)
    sys_admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    monkeypatch.setenv("ARK_API_KEY", "ark-example")
    response = client.post(
        f"/api/v1/engines/{engine.id}/entries",
        json={
            "entry_type": "api",
            "name": "豆包搜索（方舟 Responses）",
            "protocol": "doubao_search",
            "model_name": "doubao-seed-2-1-pro-260915",
            "supports_search": True,
            "supports_citation": True,
        },
        headers=auth(sys_admin),
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["protocol"] == "doubao_search"
    assert data["credential_configured"] is True
    assert "ark-example" not in response.text


def test_doubao_search_entry_requires_model_name(client, db, user_factory):
    engine = _make_engine(db)
    sys_admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    response = client.post(
        f"/api/v1/engines/{engine.id}/entries",
        json={
            "entry_type": "api",
            "name": "缺模型",
            "protocol": "doubao_search",
            "is_active": True,
        },
        headers=auth(sys_admin),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "model_name_missing"


def test_create_wenxin_search_entry(client, db, user_factory, monkeypatch):
    engine = _make_engine(db)
    sys_admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    monkeypatch.setenv("QIANFAN_API_KEY", "qf-example")
    response = client.post(
        f"/api/v1/engines/{engine.id}/entries",
        json={
            "entry_type": "api",
            "name": "文心搜索（千帆 AI 搜索）",
            "protocol": "wenxin_search",
            "supports_search": True,
            "supports_citation": True,
        },
        headers=auth(sys_admin),
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["protocol"] == "wenxin_search"
    assert data["credential_configured"] is True


def test_create_deepseek_web_search_entry(client, db, user_factory, monkeypatch):
    engine = _make_engine(db)
    sys_admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-example")
    response = client.post(
        f"/api/v1/engines/{engine.id}/entries",
        json={
            "entry_type": "api",
            "name": "DeepSeek 联网搜索（Responses 服务端工具）",
            "protocol": "deepseek_web_search",
            "model_name": "deepseek-flash",
            "supports_search": True,
            "supports_citation": True,
        },
        headers=auth(sys_admin),
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["protocol"] == "deepseek_web_search"
    assert data["credential_configured"] is True


def test_engine_manage_rejects_project_editor(client, db, user_factory):
    engine = _make_engine(db)
    editor = user_factory(f"editor-{uuid.uuid4().hex[:6]}")
    response = client.post(
        f"/api/v1/engines/{engine.id}/entries",
        json={"name": "无权限入口", "protocol": "openai_compatible"},
        headers=auth(editor),
    )
    assert response.status_code == 403


def test_patch_entry_and_test_connection_success(client, db, user_factory, monkeypatch):
    engine = _make_engine(db)
    entry = _make_entry(db, engine)
    sys_admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)

    monkeypatch.setattr(
        "app.api.engines.test_entry_connection",
        lambda _entry: {
            "success": True,
            "protocol": "openai_compatible",
            "endpoint": "https://api.deepseek.com/v1/chat/completions",
            "model_name": "deepseek-chat",
            "latency_ms": 12.3,
            "error_code": None,
            "message": "连接成功",
            "checked_at": datetime.now(timezone.utc),
        },
    )
    response = client.post(
        f"/api/v1/engines/{engine.id}/entries/{entry.id}/test-connection",
        headers=auth(sys_admin),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["success"] is True
    db.refresh(entry)
    assert entry.last_verified_at is not None
    audit = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "engine.entry.test",
            AuditLog.target_id == entry.id,
        )
    )
    assert audit is not None


def test_manual_entry_rejects_enable_before_verify(client, db, user_factory):
    """人工类入口未核验不能启用：门禁在创建 / 启用时拦截。"""
    engine = _make_engine(db, code=f"gate-{uuid.uuid4().hex[:6]}")
    sys_admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)

    response = client.post(
        f"/api/v1/engines/{engine.id}/entries",
        json={
            "entry_type": "web_user",
            "name": "未核验网页端",
            "protocol": "custom",
            "is_active": True,
        },
        headers=auth(sys_admin),
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "entry_not_verified"


def test_manual_entry_can_enable_after_verify(client, db, user_factory):
    """人工类入口先停用登记，核验通过后再启用应放行。"""
    engine = _make_engine(db, code=f"gate-{uuid.uuid4().hex[:6]}")
    sys_admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)

    created = client.post(
        f"/api/v1/engines/{engine.id}/entries",
        json={
            "entry_type": "app_search",
            "name": "应用内搜索",
            "protocol": "custom",
            "is_active": False,
        },
        headers=auth(sys_admin),
    )
    assert created.status_code == 201, created.text
    entry_id = created.json()["data"]["id"]

    verified = client.post(
        f"/api/v1/engines/{engine.id}/entries/{entry_id}/verify",
        json={"note": "已人工核验"},
        headers=auth(sys_admin),
    )
    assert verified.status_code == 200, verified.text

    enabled = client.patch(
        f"/api/v1/engines/{engine.id}/entries/{entry_id}",
        json={"is_active": True},
        headers=auth(sys_admin),
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["data"]["is_active"] is True


def test_entry_exposes_engine_supports_citation(client, db, user_factory):
    """入口记录带出所属平台的“能否返回引用来源”配置。"""
    cited = _make_engine(db, code=f"cite-{uuid.uuid4().hex[:6]}")
    cited.supports_citation = True
    db.flush()
    plain = _make_engine(db, code=f"plain-{uuid.uuid4().hex[:6]}")
    plain.supports_citation = False
    db.flush()
    sys_admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)

    cited_entry = _make_entry(db, cited, name="可看来源入口")
    plain_entry = _make_entry(db, plain, name="无来源入口")
    db.commit()

    rows = {
        row["id"]: row
        for row in client.get(
            f"/api/v1/engines/{cited.id}/entries", headers=auth(sys_admin)
        ).json()["data"]
    }
    assert rows[str(cited_entry.id)]["supports_citation"] is True

    plain_rows = {
        row["id"]: row
        for row in client.get(
            f"/api/v1/engines/{plain.id}/entries", headers=auth(sys_admin)
        ).json()["data"]
    }
    assert plain_rows[str(plain_entry.id)]["supports_citation"] is False


def test_manual_verify_web_user_entry_sets_date_and_audit(client, db, user_factory):
    engine = _make_engine(db)
    entry = _make_entry(db, engine, entry_type=EngineEntryType.WEB_USER, protocol=EngineProtocol.CUSTOM)
    sys_admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)

    response = client.post(
        f"/api/v1/engines/{engine.id}/entries/{entry.id}/verify",
        json={"note": "官网入口已人工核验"},
        headers=auth(sys_admin),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["last_verified_at"] is not None
    assert "官网入口已人工核验" in (data["access_note"] or "")
    db.refresh(entry)
    assert entry.last_verified_at is not None
    audit = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "engine.entry.manual_verify",
            AuditLog.target_id == entry.id,
        )
    )
    assert audit is not None


def test_manual_verify_rejects_api_entry(client, db, user_factory):
    engine = _make_engine(db)
    entry = _make_entry(db, engine)
    sys_admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)

    response = client.post(
        f"/api/v1/engines/{engine.id}/entries/{entry.id}/verify",
        json={},
        headers=auth(sys_admin),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "manual_verify_not_allowed"


def test_manual_verify_requires_capability(client, db, user_factory):
    engine = _make_engine(db)
    entry = _make_entry(db, engine, entry_type=EngineEntryType.APP_SEARCH, protocol=EngineProtocol.CUSTOM)
    editor = user_factory(f"editor-{uuid.uuid4().hex[:6]}")

    response = client.post(
        f"/api/v1/engines/{engine.id}/entries/{entry.id}/verify",
        json={},
        headers=auth(editor),
    )
    assert response.status_code == 403


def test_manual_verify_allows_project_editor_with_engine_verify(
    client, db, project_factory, user_factory, member_factory
):
    engine = _make_engine(db)
    entry = _make_entry(db, engine, entry_type=EngineEntryType.APP_SEARCH, protocol=EngineProtocol.CUSTOM)
    project = project_factory(f"verify-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"editor-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)

    response = client.post(
        f"/api/v1/engines/{engine.id}/entries/{entry.id}/verify",
        json={"note": "应用内搜索入口已人工核验"},
        headers=auth(editor),
    )
    assert response.status_code == 200, response.text
    assert "应用内搜索入口已人工核验" in (response.json()["data"]["access_note"] or "")


def test_connection_service_success_without_reading_answer():
    entry = SimpleNamespace(
        protocol=EngineProtocol.OPENAI_COMPATIBLE,
        entry_url="https://api.deepseek.com/v1",
        model_name="deepseek-chat",
        credential_ref=None,
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_entry_connection(entry, client=client)
    assert result["success"] is True
    assert result["error_code"] is None
    assert result["latency_ms"] is not None
    assert "pong" not in result["message"]


def test_connection_service_qianfan_adds_web_search():
    """千帆 ERNIE 对话模型的连通性探针必须带上联网开关。"""
    entry = SimpleNamespace(
        protocol=EngineProtocol.OPENAI_COMPATIBLE,
        entry_url="https://qianfan.baidubce.com/v2",
        model_name="ernie-5.1",
        credential_ref=None,
        supports_search=True,
    )
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_entry_connection(entry, client=client)
    assert result["success"] is True
    assert seen["body"]["web_search"] == {"enable": True}
    assert seen["body"]["model"] == "ernie-5.1"


def test_connection_service_spark_uses_chat_completions_and_web_search(monkeypatch):
    """星辰 MaaS 探针：走 /v2/chat/completions，参数按 Spark 规范。"""
    monkeypatch.setenv("SPARK_API_KEY", "spark-example")
    entry = SimpleNamespace(
        protocol=EngineProtocol.OPENAI_COMPATIBLE,
        entry_url="https://maas-api.cn-huabei-1.xf-yun.com/v2",
        model_name="spark-x2.6",
        credential_ref="SPARK_API_KEY",
        supports_search=True,
    )
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "code": 0,
                "choices": [{"message": {"content": "pong"}}],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_entry_connection(entry, client=client)
    assert result["success"] is True
    assert seen["url"] == "https://maas-api.cn-huabei-1.xf-yun.com/v2/chat/completions"
    assert seen["body"]["max_completion_tokens"] == 8
    assert "max_tokens" not in seen["body"]
    assert "temperature" not in seen["body"]
    assert seen["body"]["thinking"] == {"type": "disabled"}
    assert seen["body"]["tools"] == [
        {"type": "web_search", "web_search": {"enable": True}}
    ]
    assert seen["body"]["tool_choice"] == "auto"


def test_connection_service_spark_reports_business_error(monkeypatch):
    """HTTP 200 但业务 code 非 0 时，不能误报连接成功。"""
    monkeypatch.setenv("SPARK_API_KEY", "spark-example")
    entry = SimpleNamespace(
        protocol=EngineProtocol.OPENAI_COMPATIBLE,
        entry_url="https://maas-api.cn-huabei-1.xf-yun.com/v2",
        model_name="spark-x2.6",
        credential_ref="SPARK_API_KEY",
        supports_search=True,
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 10013, "message": "model not found"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_entry_connection(entry, client=client)
    assert result["success"] is False
    assert result["error_code"] == "upstream_error"
    assert "10013" in result["message"]


def test_connection_service_spark_reports_order_error(monkeypatch):
    """HTTP 403 + 11200 是账户无订单/额度，不能笼统报“鉴权失败”。"""
    monkeypatch.setenv("SPARK_API_KEY", "spark-example")
    entry = SimpleNamespace(
        protocol=EngineProtocol.OPENAI_COMPATIBLE,
        entry_url="https://maas-api.cn-huabei-1.xf-yun.com/v2",
        model_name="spark-x2.6",
        credential_ref="SPARK_API_KEY",
        supports_search=True,
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "error": {
                    "code": 11200,
                    "message": "no valid authorization: account lacks an active order",
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_entry_connection(entry, client=client)
    assert result["success"] is False
    assert result["error_code"] == "permission_denied"
    assert "11200" in result["message"]
    assert "订单" in result["message"]


def test_connection_service_qwen_uses_responses_web_search(monkeypatch):
    """千问百炼探针必须走 /responses + web_search，并检查 action.sources。"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qwen-example")
    entry = SimpleNamespace(
        protocol=EngineProtocol.OPENAI_COMPATIBLE,
        entry_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_name="qwen3.8-max",
        credential_ref=None,
        supports_search=True,
    )
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "web_search_call",
                        "status": "completed",
                        "action": {
                            "type": "search",
                            "queries": ["广州 AI 新闻"],
                            "sources": [
                                {"type": "url", "url": "https://example.com/a"},
                                {"type": "url", "url": "https://example.com/b"},
                            ],
                        },
                    },
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "pong"}],
                    },
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_entry_connection(entry, client=client)
    assert result["success"] is True
    assert seen["url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1/responses"
    assert seen["body"]["model"] == "qwen3.8-max"
    assert seen["body"]["tools"] == [{"type": "web_search"}]
    assert seen["body"]["max_output_tokens"] == 16000
    assert "enable_search" not in seen["body"]
    assert "search_options" not in seen["body"]
    assert "include" not in seen["body"]
    assert "reasoning_effort" not in seen["body"]
    assert "来源 2 条" in result["message"]


def test_connection_service_qihu360_uses_aisearch(monkeypatch):
    """360 智脑入口的探针必须走 /v1/search/aisearch，并读取 references。"""
    monkeypatch.setenv("QIHU360_API_KEY", "qihu-example")
    entry = SimpleNamespace(
        protocol=EngineProtocol.OPENAI_COMPATIBLE,
        entry_url="https://api.360.cn/v1/search",
        model_name="360gpt-pro",
        credential_ref=None,
        supports_search=True,
    )
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "id": "qihu-probe",
                "model": "360gpt-pro",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "pong[[1](https://example.com/a)]",
                        },
                    }
                ],
                "references": [
                    {
                        "rank": 1,
                        "title": "示例来源",
                        "url": "https://example.com/a",
                        "site_name": "example.com",
                        "summary_ai": "示例摘要",
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_entry_connection(entry, client=client)
    assert result["success"] is True
    assert seen["url"] == "https://api.360.cn/v1/search/aisearch"
    assert seen["body"]["model"] == "360gpt-pro"
    assert seen["body"]["search_mode"] == "required"
    assert seen["body"]["enable_corner_markers"] is True
    assert seen["body"]["max_refer_search_items"] == 10
    assert "tools" not in seen["body"]
    assert "references 1 条" in result["message"]


def test_connection_service_kimi_uses_responses_web_search(monkeypatch):
    """Kimi 入口的探针必须走 /responses + web_search，而不是 chat/completions。"""
    monkeypatch.setenv("MOONSHOT_API_KEY", "kimi-example")
    entry = SimpleNamespace(
        protocol=EngineProtocol.OPENAI_COMPATIBLE,
        entry_url="https://api.moonshot.cn/v1",
        model_name="kimi-k3",
        credential_ref=None,
        supports_search=True,
    )
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "pong"}],
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_entry_connection(entry, client=client)
    assert result["success"] is True
    assert seen["url"] == "https://api.moonshot.cn/v1/responses"
    assert seen["body"]["tools"] == [{"type": "web_search"}]
    assert seen["body"]["include"] == ["web_search_call.action.sources"]
    assert seen["body"]["reasoning_effort"] == "low"


def test_connection_service_classifies_auth_and_rate_limit():
    entry = SimpleNamespace(
        protocol=EngineProtocol.OPENAI_COMPATIBLE,
        entry_url="https://api.deepseek.com/v1",
        model_name="deepseek-chat",
        credential_ref=None,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(401)
        return httpx.Response(429)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_entry_connection(entry, client=client)
    assert result["error_code"] == "auth_failed"


def test_connection_service_rejects_unsupported_protocol():
    entry = SimpleNamespace(
        protocol=EngineProtocol.CUSTOM,
        entry_url="https://example.com/v1",
        model_name="m",
        credential_ref=None,
    )
    result = probe_entry_connection(entry)
    assert result["success"] is False
    assert result["error_code"] == "unsupported_protocol"


def test_adapter_factory_selects_openai_and_custom(db, monkeypatch):
    engine = _make_engine(db)
    custom = _make_entry(db, engine, protocol=EngineProtocol.CUSTOM, name="自定义入口")
    assert isinstance(build_entry_adapter(db, custom), UnconfiguredAdapter)

    openai = _make_entry(db, engine, name="OpenAI 入口")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    adapter = build_entry_adapter(db, openai)
    assert isinstance(adapter, OpenAICompatibleAdapter)
    assert adapter.model == "deepseek-chat"

    monkeypatch.delenv("DEEPSEEK_API_KEY")
    with pytest.raises(AccessBlockedFailure):
        build_entry_adapter(db, openai)


def test_connection_service_yuanbao_search(monkeypatch):
    entry = SimpleNamespace(
        protocol=EngineProtocol.YUANBAO_SEARCH,
        entry_url="https://wsa.tencentcloudapi.com",
        model_name="yuanbao-search",
        credential_ref="YUANBAO_SECRET_ID",
    )
    monkeypatch.setenv("YUANBAO_SECRET_ID", "AKIDEXAMPLE")
    monkeypatch.setenv("YUANBAO_SECRET_KEY", "SECRETEXAMPLE")
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["action"] = request.headers["X-TC-Action"]
        seen["auth"] = request.headers["Authorization"]
        return httpx.Response(200, json={"Response": {"Pages": [], "RequestId": "req-1"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_entry_connection(entry, client=client)
    assert result["success"] is True, result
    assert result["protocol"] == "yuanbao_search"
    assert seen["action"] == "SearchPro"
    assert seen["auth"].startswith("TC3-HMAC-SHA256 Credential=AKIDEXAMPLE/")
    assert "pong" not in result["message"]

    monkeypatch.delenv("YUANBAO_SECRET_KEY")
    result = probe_entry_connection(entry)
    assert result["error_code"] == "credential_missing"


def _probe_entry(**overrides):
    base = {
        "protocol": EngineProtocol.OPENAI_COMPATIBLE,
        "entry_url": "https://api.deepseek.com/v1",
        "model_name": "deepseek-chat",
        "credential_ref": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_connection_service_metaso_business_error_is_not_success(monkeypatch):
    monkeypatch.setenv("METASO_API_KEY", "mk-example")
    entry = _probe_entry(
        entry_url="https://metaso.cn/api/v1",
        model_name="fast",
        credential_ref="METASO_API_KEY",
        supports_search=True,
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errCode": 401, "errMsg": "bad key"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_entry_connection(entry, client=client)
    assert result["success"] is False
    assert result["error_code"] == "auth_failed"
    assert "401" in result["message"]


def test_connection_service_metaso_reads_content_and_citations(monkeypatch):
    monkeypatch.setenv("METASO_API_KEY", "mk-example")
    entry = _probe_entry(
        entry_url="https://metaso.cn/api/v1",
        model_name="fast",
        credential_ref="METASO_API_KEY",
        supports_search=True,
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "pong",
                            "citations": [{"title": "来源", "link": "https://example.com"}],
                        }
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_entry_connection(entry, client=client)
    assert result["success"] is True
    assert "回答 4 字" in result["message"]
    assert "引用 1 条" in result["message"]


def test_connection_service_zhipu_reads_web_search_sources(monkeypatch):
    """智谱探针：先独立搜索，再用入口配置的 FlashX 模型回答，不锁模型。"""
    monkeypatch.setenv("ZHIPU_API_KEY", "zhipu-example")
    entry = _probe_entry(
        entry_url="https://open.bigmodel.cn/api/paas/v4",
        model_name="glm-5.3-flashx",
        credential_ref="ZHIPU_API_KEY",
        supports_search=True,
    )
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content.decode("utf-8"))
        seen.append({"path": path, "body": body})
        if path.endswith("/web_search"):
            return httpx.Response(
                200,
                json={
                    "search_result": [
                        {
                            "title": "广州AI新闻",
                            "link": "https://example.com/a",
                            "media": "示例网",
                            "publish_date": "2026-11-20",
                            "content": "摘要",
                        },
                        {
                            "title": "重复来源",
                            "link": "https://example.com/a",
                            "media": "示例网",
                        },
                    ]
                },
            )
        if path.endswith("/chat/completions"):
            return httpx.Response(
                200,
                json={
                    "model": body["model"],
                    "choices": [{"message": {"content": "广州今天有人工智能新闻。"}}],
                },
            )
        raise AssertionError(f"unexpected path: {path}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_entry_connection(entry, client=client)

    assert result["success"] is True, result
    assert "回答 12 字" in result["message"]
    assert "来源 1 条" in result["message"]
    search_req = next(item for item in seen if item["path"].endswith("/web_search"))
    chat_req = next(item for item in seen if item["path"].endswith("/chat/completions"))
    assert search_req["body"]["search_engine"] == "search_pro"
    assert search_req["body"]["search_query"]
    assert "tools" not in search_req["body"]
    assert chat_req["body"]["model"] == "glm-5.3-flashx"
    assert "tools" not in chat_req["body"]
    assert "广州AI新闻" in chat_req["body"]["messages"][1]["content"]


def test_connection_service_zhipu_requires_sources(monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "zhipu-example")
    entry = _probe_entry(
        entry_url="https://open.bigmodel.cn/api/paas/v4",
        model_name="glm-5.3-flashx",
        credential_ref="ZHIPU_API_KEY",
        supports_search=True,
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"search_result": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_entry_connection(entry, client=client)

    assert result["success"] is False
    assert result["error_code"] == "invalid_response"
    assert "search_result" in result["message"]


def test_connection_service_zhipu_reports_search_package_balance(monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "zhipu-example")
    entry = _probe_entry(
        entry_url="https://open.bigmodel.cn/api/paas/v4",
        model_name="glm-5.3-flashx",
        credential_ref="ZHIPU_API_KEY",
        supports_search=True,
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "error": {
                    "code": "1113",
                    "message": "余额不足或无可用资源包,请充值。",
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_entry_connection(entry, client=client)

    assert result["success"] is False
    assert result["error_code"] == "insufficient_balance"
    assert "搜索" in result["message"]
    assert "资源包" in result["message"]
    assert "充值" in result["message"]


def test_connection_service_validates_missing_fields(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert probe_entry_connection(_probe_entry(entry_url=None))["error_code"] == "entry_url_missing"
    assert probe_entry_connection(_probe_entry(model_name=None))["error_code"] == "model_name_missing"
    assert (
        probe_entry_connection(_probe_entry(credential_ref="DEEPSEEK_API_KEY"))["error_code"]
        == "credential_missing"
    )


def test_connection_service_classifies_network_errors():
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        result = probe_entry_connection(_probe_entry(), client=client)
    assert result["error_code"] == "timeout"

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with httpx.Client(transport=httpx.MockTransport(unreachable)) as client:
        result = probe_entry_connection(_probe_entry(), client=client)
    assert result["error_code"] == "unreachable"


@pytest.mark.parametrize(
    "status, code",
    [
        (404, "endpoint_not_found"),
        (500, "upstream_error"),
        (400, "http_error"),
        (429, "rate_limited"),
    ],
)
def test_connection_service_classifies_http_status(status, code):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_entry_connection(_probe_entry(), client=client)
    assert result["success"] is False
    assert result["error_code"] == code


def test_list_and_patch_entry(client, db, user_factory):
    engine = _make_engine(db)
    entry = _make_entry(db, engine)
    sys_admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    headers = auth(sys_admin)

    listed = client.get(f"/api/v1/engines/{engine.id}/entries", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["meta"]["total"] == 1

    patched = client.patch(
        f"/api/v1/engines/{engine.id}/entries/{entry.id}",
        json={"access_note": "运营已核验", "model_name": "deepseek-chat"},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["access_note"] == "运营已核验"


def test_entry_create_validation_and_conflict(client, db, user_factory):
    engine = _make_engine(db)
    sys_admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    headers = auth(sys_admin)

    bad_url = client.post(
        f"/api/v1/engines/{engine.id}/entries",
        json={"name": "bad-url", "entry_url": "ftp://example.com"},
        headers=headers,
    )
    assert bad_url.status_code == 422

    bad_ref = client.post(
        f"/api/v1/engines/{engine.id}/entries",
        json={"name": "bad-ref", "credential_ref": "sk-plaintext"},
        headers=headers,
    )
    assert bad_ref.status_code == 422

    missing_model = client.post(
        f"/api/v1/engines/{engine.id}/entries",
        json={
            "name": "missing-model",
            "entry_url": "https://api.deepseek.com/v1",
            "protocol": "openai_compatible",
            "is_active": True,
        },
        headers=headers,
    )
    assert missing_model.status_code == 400
    assert missing_model.json()["error"]["code"] == "model_name_missing"

    payload = {
        "name": "duplicate",
        "entry_url": "https://api.deepseek.com/v1",
        "protocol": "openai_compatible",
        "model_name": "deepseek-chat",
    }
    assert client.post(f"/api/v1/engines/{engine.id}/entries", json=payload, headers=headers).status_code == 201
    duplicate = client.post(f"/api/v1/engines/{engine.id}/entries", json=payload, headers=headers)
    assert duplicate.status_code == 400
    assert duplicate.json()["error"]["code"] == "engine_entry_exists"


def test_entry_missing_engine_or_entry(client, db, user_factory):
    sys_admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    headers = auth(sys_admin)
    missing = uuid.uuid4()
    assert client.get(f"/api/v1/engines/{missing}/entries", headers=headers).status_code == 404

    engine = _make_engine(db)
    assert (
        client.patch(
            f"/api/v1/engines/{engine.id}/entries/{uuid.uuid4()}",
            json={"access_note": "x"},
            headers=headers,
        ).status_code
        == 404
    )


def test_engine_catalog_requires_engine_capability(
    client, db, project_factory, user_factory, member_factory
):
    """目录是全局配置，普通登录用户（含项目只读）不得枚举。"""
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"engvis-{suffix}")
    viewer = user_factory(f"engvis-viewer-{suffix}")
    editor = user_factory(f"engvis-editor-{suffix}")
    outsider = user_factory(f"engvis-outsider-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)
    member_factory(project, editor, RoleCode.EDITOR)
    engine = _make_engine(db)
    _make_entry(db, engine)

    assert client.get("/api/v1/engines", headers=auth(outsider)).status_code == 403
    assert client.get("/api/v1/engines", headers=auth(viewer)).status_code == 403
    assert (
        client.get(f"/api/v1/engines/{engine.id}/entries", headers=auth(viewer)).status_code == 403
    )

    assert client.get("/api/v1/engines", headers=auth(editor)).status_code == 200
    assert (
        client.get(f"/api/v1/engines/{engine.id}/entries", headers=auth(editor)).status_code == 200
    )


def test_engine_entry_list_redacts_api_config_for_project_editor(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    """运营能看入口清单和人工核验地址，但不能拿到 API 入口 URL / 凭据变量名。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"engred-{suffix}")
    editor = user_factory(f"engred-editor-{suffix}")
    sys_admin = user_factory(f"engred-sys-{suffix}", is_system_admin=True)
    member_factory(project, editor, RoleCode.EDITOR)
    engine = _make_engine(db)
    api_entry = _make_entry(db, engine, name="API 入口", entry_url="https://api.example.com/v1")
    web_entry = _make_entry(
        db,
        engine,
        entry_type=EngineEntryType.WEB_USER,
        name="网页用户端",
        entry_url="https://chat.example.com",
        credential_ref=None,
    )
    db.commit()

    response = client.get(f"/api/v1/engines/{engine.id}/entries", headers=auth(editor))
    assert response.status_code == 200, response.text
    rows = {row["id"]: row for row in response.json()["data"]}
    api_row = rows[str(api_entry.id)]
    assert api_row["entry_url"] is None
    assert api_row["credential_ref"] is None
    assert api_row["config_redacted"] is True
    assert api_row["credential_configured"] is False
    web_row = rows[str(web_entry.id)]
    assert web_row["entry_url"] == "https://chat.example.com"
    assert web_row["credential_ref"] is None
    assert web_row["config_redacted"] is True

    admin_response = client.get(
        f"/api/v1/engines/{engine.id}/entries", headers=auth(sys_admin)
    )
    assert admin_response.status_code == 200, admin_response.text
    admin_rows = {row["id"]: row for row in admin_response.json()["data"]}
    assert admin_rows[str(api_entry.id)]["entry_url"] == "https://api.example.com/v1"
    assert admin_rows[str(api_entry.id)]["credential_ref"] == "DEEPSEEK_API_KEY"
    assert admin_rows[str(api_entry.id)]["config_redacted"] is False


def test_credential_ref_rejects_uncontrolled_env_name(client, db, user_factory):
    engine = _make_engine(db)
    sys_admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    response = client.post(
        f"/api/v1/engines/{engine.id}/entries",
        json={"name": "evil-ref", "credential_ref": "PATH"},
        headers=auth(sys_admin),
    )
    assert response.status_code == 422


def test_unused_engine_entry_can_be_deleted(client, db, user_factory):
    """误建的入口（模型）允许单独删除，平台本身保留。"""
    engine = _make_engine(db)
    entry = _make_entry(db, engine)
    sys_admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)

    response = client.delete(
        f"/api/v1/engines/{engine.id}/entries/{entry.id}", headers=auth(sys_admin)
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"] == {"id": str(entry.id), "deleted": True}

    assert db.scalar(select(AiEngineEntry).where(AiEngineEntry.id == entry.id)) is None
    assert db.scalar(select(AiEngine).where(AiEngine.id == engine.id)) is not None
    assert (
        db.scalar(
            select(AuditLog).where(
                AuditLog.action == "engine.entry.delete",
                AuditLog.target_id == entry.id,
            )
        )
        is not None
    )


def test_engine_platform_delete_is_not_provided(client, db, user_factory):
    """平台目录不提供删除：误建只删入口，避免整条平台被误删。"""
    engine = _make_engine(db)
    sys_admin = user_factory(f"sys-{uuid.uuid4().hex[:6]}", is_system_admin=True)

    response = client.delete(f"/api/v1/engines/{engine.id}", headers=auth(sys_admin))
    assert response.status_code in (404, 405), response.text
    assert db.scalar(select(AiEngine).where(AiEngine.id == engine.id)) is not None
