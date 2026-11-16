"""DeepSeek 网页版联网搜索适配器单测：结果归一、引用去重、失败分类与构建校验。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.models.enums import FailureCode
from app.services.deepseek_websearch_adapter import (
    DeepSeekWebsearchAdapter,
    LoginBlockedFailure,
    build_deepseek_websearch_adapter,
)
from app.services.monitoring_collection import (
    AccessBlockedFailure,
    CollectionFailure,
    RateLimitedFailure,
    TransientCollectionFailure,
)
from app.services.monitoring_extraction import AnswerPayload


class _DummyDB:
    def get(self, _model: object, _key: object) -> SimpleNamespace:
        return SimpleNamespace(text="广东省AI数字人才就业实训基地在广州哪里，怎么报名？")


class _FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise ValueError("not json")
        return self._payload


class _FakeClient:
    def __init__(self, response: _FakeResponse | Exception) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any]) -> _FakeResponse:
        self.calls.append({"method": "POST", "url": url, "headers": headers, "json": json})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def get(self, url: str, *, headers: dict[str, str]) -> _FakeResponse:
        self.calls.append({"method": "GET", "url": url, "headers": headers})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _adapter(client: _FakeClient, *, token: str = "") -> DeepSeekWebsearchAdapter:
    return DeepSeekWebsearchAdapter(
        _DummyDB(),  # type: ignore[arg-type]
        bridge_url="http://127.0.0.1:8099",
        token=token,
        client=client,  # type: ignore[arg-type]
    )


def _task() -> SimpleNamespace:
    return SimpleNamespace(question_version_id="qv-1")


def test_collect_parses_answer_and_citations() -> None:
    client = _FakeClient(
        _FakeResponse(
            {
                "logged_in": True,
                "model_name": "deepseek-websearch",
                "answer": "广东省AI数字人才就业实训基地在广州番禺。-\n9\n\n报名电话：13022038683。-\n1",
                "citations": [
                    {"url": "https://www.b2b168.org/card/a", "title": "A"},
                    {"url": "https://www.b2b168.org/card/a", "title": "A 重复"},
                    {"url": "https://www.sohu.com/a/1"},
                ],
                "searched_page_count": 11,
                "session_url": "https://chat.deepseek.com/a/chat/s/abc",
                "elapsed_ms": 42_000,
            }
        )
    )
    payload = _adapter(client).collect(_task())  # type: ignore[arg-type]

    assert isinstance(payload, AnswerPayload)
    assert payload.text.startswith("广东省AI数字人才就业实训基地在广州番禺。[9]")
    assert "报名电话：13022038683。[1]" in payload.text
    assert payload.engine_model == "deepseek-websearch"
    assert [item.url for item in payload.citations] == [
        "https://www.b2b168.org/card/a",
        "https://www.sohu.com/a/1",
    ]
    assert payload.raw_response["searched_page_count"] == 11
    assert payload.raw_response["session_url"].endswith("/abc")
    call = client.calls[0]
    assert call["url"] == "http://127.0.0.1:8099/collect"
    assert call["json"]["question"] == "广东省AI数字人才就业实训基地在广州哪里，怎么报名？"


def test_collect_maps_login_required() -> None:
    client = _FakeClient(
        _FakeResponse({"error": "login_required", "logged_in": False}, status_code=409)
    )
    with pytest.raises(LoginBlockedFailure) as exc:
        _adapter(client).collect(_task())  # type: ignore[arg-type]
    assert exc.value.failure_code == FailureCode.LOGIN_BLOCKED
    assert exc.value.retryable is False


def test_collect_maps_rate_limit_and_timeout() -> None:
    with pytest.raises(RateLimitedFailure):
        _adapter(_FakeClient(_FakeResponse({"error": "rate_limited"}, status_code=429))).collect(
            _task()  # type: ignore[arg-type]
        )
    with pytest.raises(TransientCollectionFailure) as exc:
        _adapter(_FakeClient(_FakeResponse({"error": "timeout"}, status_code=504))).collect(
            _task()  # type: ignore[arg-type]
        )
    assert exc.value.failure_code == FailureCode.TIMEOUT
    assert exc.value.retryable is True


def test_collect_maps_unreachable_bridge() -> None:
    client = _FakeClient(httpx.ConnectError("connection refused"))
    with pytest.raises(AccessBlockedFailure):
        _adapter(client).collect(_task())  # type: ignore[arg-type]


def test_collect_rejects_empty_answer() -> None:
    client = _FakeClient(_FakeResponse({"logged_in": True, "answer": "  ", "citations": []}))
    with pytest.raises(CollectionFailure) as exc:
        _adapter(client).collect(_task())  # type: ignore[arg-type]
    assert exc.value.failure_code == FailureCode.OTHER
    assert exc.value.retryable is False


def test_collect_with_request_uses_stored_question() -> None:
    client = _FakeClient(_FakeResponse({"logged_in": True, "answer": "回答正文" * 12}))
    _adapter(client).collect_with_request(  # type: ignore[arg-type]
        _task(),
        {"question": "留存的原始问法"},
    )
    assert client.calls[0]["json"]["question"] == "留存的原始问法"


def test_health_reports_login_state() -> None:
    client = _FakeClient(_FakeResponse({"ok": True, "logged_in": False}))
    assert _adapter(client).health()["logged_in"] is False
    assert client.calls[0]["url"] == "http://127.0.0.1:8099/health"


def test_build_requires_bridge_url_and_optional_token(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(AccessBlockedFailure):
        build_deepseek_websearch_adapter(_DummyDB(), entry_url=None)  # type: ignore[arg-type]

    adapter = build_deepseek_websearch_adapter(
        _DummyDB(),  # type: ignore[arg-type]
        entry_url=None,
        bridge_url_fallback="http://127.0.0.1:8099",
        client=_FakeClient(_FakeResponse({"logged_in": True})),  # type: ignore[arg-type]
    )
    assert adapter.bridge_url == "http://127.0.0.1:8099"
    adapter.close()

    monkeypatch.delenv("DEEPSEEK_WEBSEARCH_TOKEN", raising=False)
    with pytest.raises(AccessBlockedFailure):
        build_deepseek_websearch_adapter(
            _DummyDB(),  # type: ignore[arg-type]
            entry_url="http://127.0.0.1:8099",
            credential_ref="DEEPSEEK_WEBSEARCH_TOKEN",
        )

    monkeypatch.setenv("DEEPSEEK_WEBSEARCH_TOKEN", "bridge-token")
    adapter = build_deepseek_websearch_adapter(
        _DummyDB(),  # type: ignore[arg-type]
        entry_url="http://127.0.0.1:8099",
        credential_ref="DEEPSEEK_WEBSEARCH_TOKEN",
        client=_FakeClient(_FakeResponse({"logged_in": True})),  # type: ignore[arg-type]
    )
    assert adapter.token == "bridge-token"
    adapter.close()
