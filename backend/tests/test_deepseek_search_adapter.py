"""DeepSeek 官方搜索适配器（/v1/tools/search）的单元测试。"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.services.deepseek_search_adapter import (
    DEFAULT_ENDPOINT,
    DeepSeekSearchAdapter,
)
from app.services.monitoring_collection import (
    AccessBlockedFailure,
    CollectionFailure,
    RateLimitedFailure,
)


class _FakeDB:
    def __init__(self, text: str) -> None:
        self._version = SimpleNamespace(text=text)

    def get(self, *_args, **_kwargs):
        return self._version


def _task() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        question_version_id=uuid.uuid4(),
    )


def _adapter(handler) -> DeepSeekSearchAdapter:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return DeepSeekSearchAdapter(
        _FakeDB("广州有哪些 AI 实训基地"),
        api_key="sk-test",
        client=client,
    )


def test_collect_maps_results_to_text_and_citations():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(DEFAULT_ENDPOINT)
        assert request.headers["authorization"] == "Bearer sk-test"
        body = request.read().decode("utf-8")
        assert '"query"' in body and '"count"' in body
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "广州 AI 实训基地盘点",
                        "url": "https://example.com/a",
                        "snippet": "摘要 A",
                        "summary": "长摘要 A",
                    },
                    {
                        "title": "第二篇",
                        "url": "https://example.com/b",
                        "summary": "长摘要 B",
                    },
                ]
            },
        )

    payload = _adapter(handler).collect(_task())
    assert payload.engine_model == "deepseek-search"
    assert payload.raw_response["answer_kind"] == "search_result"
    assert payload.raw_response["result_count"] == 2
    assert "[1] 广州 AI 实训基地盘点" in payload.text
    assert "https://example.com/b" in payload.text
    assert [item.url for item in payload.citations] == [
        "https://example.com/a",
        "https://example.com/b",
    ]


def test_empty_results_is_valid_answer_not_error():
    payload = _adapter(lambda request: httpx.Response(200, json={"results": []})).collect(
        _task()
    )
    assert payload.text == ""
    assert payload.citations == []
    assert payload.raw_response["result_count"] == 0


def test_rate_limit_429_raises_rate_limited():
    with pytest.raises(RateLimitedFailure):
        _adapter(lambda request: httpx.Response(429, json={})).collect(_task())


def test_auth_failure_is_access_blocked():
    with pytest.raises(AccessBlockedFailure):
        _adapter(lambda request: httpx.Response(401, json={})).collect(_task())


def test_insufficient_balance_is_access_blocked():
    with pytest.raises(AccessBlockedFailure) as excinfo:
        _adapter(lambda request: httpx.Response(402, json={})).collect(_task())
    assert "402" in str(excinfo.value)


def test_bad_request_is_non_retryable():
    with pytest.raises(CollectionFailure) as excinfo:
        _adapter(lambda request: httpx.Response(400, json={})).collect(_task())
    assert excinfo.value.retryable is False


def test_question_longer_than_limit_rejected_before_request():
    called = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["count"] += 1
        return httpx.Response(200, json={"results": []})

    adapter = DeepSeekSearchAdapter(
        _FakeDB("问" * 129), api_key="sk-test", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(CollectionFailure):
        adapter.collect(_task())
    assert called["count"] == 0
