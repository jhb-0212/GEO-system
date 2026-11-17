"""DeepSeek 服务端联网搜索（Responses + deepseek_web_search）适配器单测。"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.services.deepseek_web_search_adapter import (
    DEFAULT_ENDPOINT,
    DeepSeekWebSearchAdapter,
    build_deepseek_web_search_adapter,
)
from app.services.monitoring_collection import (
    AccessBlockedFailure,
    CollectionFailure,
    RateLimitedFailure,
    TransientCollectionFailure,
)


class _FakeDB:
    def __init__(self, text: str = "广州有哪些人工智能实训基地") -> None:
        self._version = SimpleNamespace(text=text)

    def get(self, *_args, **_kwargs):
        return self._version


def _task() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), question_version_id=uuid.uuid4())


def _adapter(handler, model: str | None = None):
    return DeepSeekWebSearchAdapter(
        _FakeDB(),
        api_key="ds-test",
        model=model or "deepseek-flash",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _body_with(annotations: list[dict], text: str = "广州有多家 AI 实训基地") -> dict:
    return {
        "id": "resp-test",
        "model": "deepseek-flash",
        "status": "completed",
        "output": [
            {"type": "reasoning", "id": "rs-1", "summary": []},
            {
                "type": "web_search_call",
                "id": "srvtoolu-1",
                "status": "completed",
                "kind": "deep_search",
                "action": {
                    "type": "search",
                    "queries": ["广州 AI 实训基地", "广州 人工智能 公共实训"],
                },
            },
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": text, "annotations": annotations}
                ],
            },
        ],
        "usage": {
            "input_tokens": 1200,
            "output_tokens": 300,
            "total_tokens": 1500,
            "server_tool_use": {"tool_search": 2, "tool_fetch": 0},
        },
    }


def test_collect_parses_answer_and_citations():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["authorization"]
        captured["body"] = json.loads(request.read().decode("utf-8"))
        return httpx.Response(
            200,
            json=_body_with(
                [
                    {"type": "url_citation", "url": "https://example.com/a", "title": "A"},
                    {"type": "url_citation", "url": "https://example.com/a", "title": "重复"},
                    {"type": "url_citation", "url": "https://example.com/b"},
                    {"type": "other", "url": "https://example.com/c"},
                ]
            ),
        )

    payload = _adapter(handler).collect(_task())
    assert captured["url"] == DEFAULT_ENDPOINT
    assert captured["auth"] == "Bearer ds-test"
    assert captured["body"]["tools"] == [{"type": "deepseek_web_search"}]
    assert captured["body"]["stream"] is False
    assert captured["body"]["model"] == "deepseek-flash"
    assert payload.raw_response["answer_kind"] == "answer"
    assert payload.raw_response["citation_count"] == 2
    assert [c.url for c in payload.citations] == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert payload.raw_response["search_actions"][0]["queries"] == [
        "广州 AI 实训基地",
        "广州 人工智能 公共实训",
    ]
    assert payload.prompt_tokens == 1200
    assert payload.total_tokens == 1500
    assert payload.engine_model == "deepseek-flash"


def test_answer_without_annotations_still_valid():
    payload = _adapter(lambda request: httpx.Response(200, json=_body_with([]))).collect(
        _task()
    )
    assert payload.citations == []
    assert payload.raw_response["citation_count"] == 0


def test_missing_output_is_transient_failure():
    with pytest.raises(TransientCollectionFailure):
        _adapter(lambda request: httpx.Response(200, json={"id": "resp"})).collect(_task())


def test_empty_answer_text_is_transient_failure():
    body = _body_with([], text="   ")
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


def test_error_body_is_not_swallowed():
    with pytest.raises(CollectionFailure) as excinfo:
        _adapter(
            lambda request: httpx.Response(
                200, json={"error": {"code": "invalid_request", "message": "bad tools"}}
            )
        ).collect(_task())
    assert "bad tools" in str(excinfo.value)


def test_builder_requires_env(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(AccessBlockedFailure):
        build_deepseek_web_search_adapter(
            _FakeDB(), credential_ref=None, model_name=None
        )
