"""豆包搜索（方舟 Responses + web_search）适配器的单元测试。"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.services.doubao_search_adapter import (
    DEFAULT_ENDPOINT,
    DEFAULT_LIMIT,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MAX_TOOL_CALLS,
    DoubaoSearchAdapter,
    build_doubao_search_adapter,
)
from app.services.monitoring_collection import (
    AccessBlockedFailure,
    CollectionFailure,
    RateLimitedFailure,
    TransientCollectionFailure,
)


class _FakeDB:
    def __init__(self, text: str = "广州有哪些 AI 实训基地") -> None:
        self._version = SimpleNamespace(text=text)

    def get(self, *_args, **_kwargs):
        return self._version


def _task() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), question_version_id=uuid.uuid4())


def _adapter(handler) -> DoubaoSearchAdapter:
    return DoubaoSearchAdapter(
        _FakeDB(),
        api_key="ark-test",
        model="doubao-seed-2-1-pro-260915",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _response_body() -> dict:
    return {
        "id": "resp_test",
        "object": "response",
        "model": "doubao-seed-2-1-pro-260915",
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": [{"type": "summary_text", "text": "先搜索"}]},
            {
                "type": "web_search_call",
                "status": "completed",
                "action": {"type": "search", "query": "广州 AI 实训基地", "queries": ["广州 AI 实训基地"]},
            },
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": "广州有多家 AI 实训基地，例如……",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "title": "广州 AI 实训基地盘点",
                                "url": "https://example.com/a",
                                "site_name": "示例站点",
                                "publish_time": "2026-09-04T10:24:00+08:00",
                                "summary": "摘要 A",
                                },
                            {
                                "type": "url_citation",
                                "title": "重复引用同一 URL",
                                "url": "https://example.com/a",
                            },
                            {
                                "type": "url_citation",
                                "title": "第二篇",
                                "url": "https://example.com/b",
                            },
                        ],
                    }
                ],
            },
        ],
        "usage": {"input_tokens": 3666, "output_tokens": 1610, "total_tokens": 5276},
    }


def test_collect_parses_answer_and_citations():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["authorization"]
        captured["body"] = json.loads(request.read().decode("utf-8"))
        return httpx.Response(200, json=_response_body())

    payload = _adapter(handler).collect(_task())
    assert captured["url"] == DEFAULT_ENDPOINT
    assert captured["auth"] == "Bearer ark-test"
    # limit 固定下发、store 显式 false、max_tool_calls 显式下发：口径固定的一部分，不能随手删
    assert captured["body"]["tools"] == [{"type": "web_search", "limit": DEFAULT_LIMIT}]
    assert captured["body"]["store"] is False
    assert captured["body"]["max_tool_calls"] == DEFAULT_MAX_TOOL_CALLS
    # 不设输出上限会按模型默认生成长答案，单次可拖到 120 秒超时；必须显式封顶。
    assert captured["body"]["max_output_tokens"] == DEFAULT_MAX_OUTPUT_TOKENS
    assert captured["body"]["stream"] is False
    assert "广州有多家 AI 实训基地" in payload.text
    assert payload.raw_response["answer_kind"] == "answer"
    assert payload.raw_response["search_queries"] == ["广州 AI 实训基地"]
    assert [item.url for item in payload.citations] == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert payload.prompt_tokens == 3666
    assert payload.completion_tokens == 1610
    assert payload.total_tokens == 5276
    assert payload.engine_model == "doubao-seed-2-1-pro-260915"


def test_answer_without_annotations_has_zero_citations():
    body = _response_body()
    body["output"] = [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "未联网直接回答"}],
        }
    ]
    payload = _adapter(lambda request: httpx.Response(200, json=body)).collect(_task())
    assert payload.citations == []
    assert payload.raw_response["citation_count"] == 0
    assert payload.raw_response["search_queries"] == []


def test_search_sources_come_from_tool_usage_details():
    """来源归因只认 usage.tool_usage_details；action 里没有 source（实测确认）。"""
    body = _response_body()
    body["usage"] = {
        "input_tokens": 3666,
        "output_tokens": 1610,
        "total_tokens": 5276,
        "tool_usage": {"web_search": 9},
        "tool_usage_details": {"web_search": {"search_engine": 9}},
    }
    payload = _adapter(lambda request: httpx.Response(200, json=body)).collect(_task())
    assert payload.raw_response["search_sources"] == {"search_engine": 9}
    assert payload.raw_response["search_source_names"] == ["search_engine"]


def test_search_call_records_queries_even_without_source():
    body = _response_body()
    body["output"] = [
        {
            "type": "web_search_call",
            "status": "completed",
            "action": {"type": "search", "query": "广州 AI 实训基地"},
        },
        {
            "type": "web_search_call",
            "status": "completed",
            "action": {"type": "search", "query": "番禺 AI 培训"},
        },
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "回答正文"}],
        },
    ]
    payload = _adapter(lambda request: httpx.Response(200, json=body)).collect(_task())
    assert [c["query"] for c in payload.raw_response["search_calls"]] == [
        "广州 AI 实训基地",
        "番禺 AI 培训",
    ]
    assert payload.raw_response["web_search_calls"] == 2
    # 没有 tool_usage_details 时如实为空，不伪造来源
    assert payload.raw_response["search_sources"] == {}


def test_search_scope_marks_generic_engine_by_default():
    """未限定 sources 时走联网内容插件的 search_engine，必须显式标出来。"""
    payload = _adapter(lambda request: httpx.Response(200, json=_response_body())).collect(_task())
    assert payload.raw_response["search_scope"] == "search_engine"
    assert payload.raw_response["search_limit"] == DEFAULT_LIMIT
    assert payload.raw_response["max_tool_calls"] == DEFAULT_MAX_TOOL_CALLS


def test_search_scope_lists_explicit_sources():
    adapter = DoubaoSearchAdapter(
        _FakeDB(),
        api_key="ark-test",
        model="doubao-seed-2-1-pro-260915",
        sources=("doubao",),
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=_response_body()))),
    )
    payload = adapter.collect(_task())
    assert payload.raw_response["search_scope"] == "doubao"
    assert adapter.last_request_payload["tools"] == [
        {"type": "web_search", "limit": DEFAULT_LIMIT, "sources": ["doubao"]}
    ]


def test_limit_outside_documented_range_is_rejected():
    with pytest.raises(ValueError):
        DoubaoSearchAdapter(
            _FakeDB(),
            api_key="ark-test",
            model="doubao-seed-2-1-pro-260915",
            limit=0,
        )
    with pytest.raises(ValueError):
        DoubaoSearchAdapter(
            _FakeDB(),
            api_key="ark-test",
            model="doubao-seed-2-1-pro-260915",
            limit=51,
        )


def test_max_tool_calls_outside_documented_range_is_rejected():
    with pytest.raises(ValueError):
        DoubaoSearchAdapter(
            _FakeDB(),
            api_key="ark-test",
            model="doubao-seed-2-1-pro-260915",
            max_tool_calls=0,
        )
    with pytest.raises(ValueError):
        DoubaoSearchAdapter(
            _FakeDB(),
            api_key="ark-test",
            model="doubao-seed-2-1-pro-260915",
            max_tool_calls=11,
        )


def test_replay_payload_without_store_gets_store_false():
    """回放历史请求体时补 store:false，避免老口径在方舟侧继续留存。"""
    captured = {}
    legacy = {
        "model": "doubao-seed-2-1-pro-260915",
        "tools": [{"type": "web_search"}],
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "老请求体"}]}],
        "stream": False,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.read().decode("utf-8"))
        return httpx.Response(200, json=_response_body())

    adapter = _adapter(handler)
    payload = adapter.collect_with_request(_task(), legacy)
    # 回放不改用户留存的其他字段，只补 store
    assert captured["body"]["tools"] == [{"type": "web_search"}]
    assert captured["body"]["store"] is False
    assert payload.raw_response["answer_kind"] == "answer"


def test_no_answer_text_is_transient_failure():
    body = {"output": [{"type": "reasoning", "summary": []}]}
    with pytest.raises(TransientCollectionFailure):
        _adapter(lambda request: httpx.Response(200, json=body)).collect(_task())


def test_rate_limit_429():
    with pytest.raises(RateLimitedFailure):
        _adapter(lambda request: httpx.Response(429, json={})).collect(_task())


def test_auth_failure_401():
    with pytest.raises(AccessBlockedFailure):
        _adapter(lambda request: httpx.Response(401, json={})).collect(_task())


def test_bad_request_is_non_retryable():
    with pytest.raises(CollectionFailure) as excinfo:
        _adapter(lambda request: httpx.Response(400, json={})).collect(_task())
    assert excinfo.value.retryable is False


def test_web_search_denied_is_access_blocked():
    body = {
        "error": {
            "code": "AccessDenied",
            "message": "Access denied for web search. Please go to the Volcano Ark Console.",
            "type": "Forbidden",
        }
    }
    with pytest.raises(AccessBlockedFailure) as excinfo:
        _adapter(lambda request: httpx.Response(403, json=body)).collect(_task())
    assert "联网搜索未开通" in str(excinfo.value)


def test_model_not_open_is_access_blocked():
    body = {
        "error": {
            "code": "ModelNotOpen",
            "message": "Your account has not activated the model.",
            "type": "Not Found",
        }
    }
    with pytest.raises(AccessBlockedFailure) as excinfo:
        _adapter(lambda request: httpx.Response(404, json=body)).collect(_task())
    message = str(excinfo.value)
    assert "模型未开通" in message
    assert "ModelNotOpen" in message


def test_unknown_404_stays_non_retryable():
    body = {"error": {"code": "InvalidParameter", "message": "bad input"}}
    with pytest.raises(CollectionFailure) as excinfo:
        _adapter(lambda request: httpx.Response(404, json=body)).collect(_task())
    assert excinfo.value.retryable is False
    assert "InvalidParameter" in str(excinfo.value)


def test_builder_requires_model_name(monkeypatch):
    monkeypatch.setenv("ARK_API_KEY", "ark-test")
    with pytest.raises(AccessBlockedFailure):
        build_doubao_search_adapter(
            _FakeDB(),
            credential_ref=None,
            model_name=None,
        )
