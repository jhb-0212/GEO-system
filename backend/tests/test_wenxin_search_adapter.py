"""文心/千帆 AI 搜索适配器的单元测试。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.services.monitoring_collection import (
    AccessBlockedFailure,
    CollectionFailure,
    RateLimitedFailure,
    TransientCollectionFailure,
)
from app.services.wenxin_search_adapter import (
    DEFAULT_ENDPOINT,
    WenxinSearchAdapter,
)


class _FakeDB:
    def __init__(self, text: str = "广州有哪些 AI 实训基地") -> None:
        self._version = SimpleNamespace(text=text)

    def get(self, *_args, **_kwargs):
        return self._version


def _task() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), question_version_id=uuid.uuid4())


def _adapter(handler) -> WenxinSearchAdapter:
    return WenxinSearchAdapter(
        _FakeDB(),
        api_key="qf-test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_collect_parses_references_to_text_and_citations():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["authorization"]
        captured["body"] = json.loads(request.read().decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "request_id": "req-test",
                "references": [
                    {
                        "id": 1,
                        "title": "广州 AI 实训基地盘点",
                        "url": "https://example.com/a",
                        "snippet": "摘要 A",
                        "date": "2026-09-04",
                        "website": "示例站点",
                    },
                    {"title": "重复链接", "url": "https://example.com/a"},
                    {"url": "https://example.com/b"},
                    "https://example.com/c",
                ],
            },
        )

    payload = _adapter(handler).collect(_task())
    assert captured["url"] == DEFAULT_ENDPOINT
    assert captured["auth"] == "Bearer qf-test"
    assert captured["body"] == {
        "messages": [{"role": "user", "content": "广州有哪些 AI 实训基地"}]
    }
    assert payload.raw_response["answer_kind"] == "search_result"
    assert payload.raw_response["result_count"] == 4
    assert "[1] 广州 AI 实训基地盘点" in payload.text
    assert "https://example.com/c" in payload.text
    assert [item.url for item in payload.citations] == [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    ]
    first = payload.citations[0]
    assert first.title == "广州 AI 实训基地盘点"
    assert first.site_name == "示例站点"
    assert first.snippet == "摘要 A"
    assert first.published_at == datetime(2026, 9, 4, tzinfo=timezone.utc)


def test_empty_references_is_valid_answer():
    payload = _adapter(
        lambda request: httpx.Response(200, json={"references": [], "request_id": "req"})
    ).collect(_task())
    assert payload.text == ""
    assert payload.citations == []
    assert payload.raw_response["result_count"] == 0


def test_missing_references_is_transient_failure():
    with pytest.raises(TransientCollectionFailure):
        _adapter(lambda request: httpx.Response(200, json={"request_id": "req"})).collect(
            _task()
        )


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
                200, json={"error": {"code": "InvalidApiKey", "message": "invalid key"}}
            )
        ).collect(_task())
    assert "invalid key" in str(excinfo.value)
