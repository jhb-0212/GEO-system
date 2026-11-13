"""元宝搜索适配器单测：签名头、结果归一、错误分类。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.models.enums import FailureCode
from app.services.monitoring_collection import AccessBlockedFailure, RateLimitedFailure
from app.services.monitoring_extraction import AnswerPayload
from app.services.yuanbao_search_adapter import (
    SECRET_KEY_ENV,
    YuanbaoSearchAdapter,
    build_tc3_headers,
    build_yuanbao_adapter,
)


class _DummyDB:
    def get(self, _model: object, _key: object) -> SimpleNamespace:
        return SimpleNamespace(text="广州基地在生成式搜索里的表现如何？")


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, *, headers: dict[str, str], content: bytes) -> _FakeResponse:
        self.calls.append({"url": url, "headers": headers, "content": content})
        return self.response


def _adapter(client: _FakeClient) -> YuanbaoSearchAdapter:
    return YuanbaoSearchAdapter(
        _DummyDB(),  # type: ignore[arg-type]
        secret_id="AKIDEXAMPLE",
        secret_key="SECRETEXAMPLE",
        endpoint="https://wsa.tencentcloudapi.com",
        client=client,  # type: ignore[arg-type]
    )


def test_build_tc3_headers_has_expected_shape() -> None:
    headers = build_tc3_headers(
        secret_id="AKIDEXAMPLE",
        secret_key="SECRETEXAMPLE",
        action="SearchPro",
        version="2025-05-08",
        endpoint="https://wsa.tencentcloudapi.com",
        body=b'{"Query":"ping","Cnt":10}',
        timestamp=1_760_000_000,
    )
    assert headers["X-TC-Action"] == "SearchPro"
    assert headers["X-TC-Version"] == "2025-05-08"
    assert headers["X-TC-Timestamp"] == "1760000000"
    assert headers["Host"] == "wsa.tencentcloudapi.com"
    assert headers["Authorization"].startswith(
        "TC3-HMAC-SHA256 Credential=AKIDEXAMPLE/2025-10-09/wsa/tc3_request"
    )
    assert "SignedHeaders=content-type;host;x-tc-action" in headers["Authorization"]
    assert "Signature=" in headers["Authorization"]


def test_collect_parses_pages_and_citations() -> None:
    client = _FakeClient(
        _FakeResponse(
            {
                "Response": {
                    "Query": "广州基地",
                    "Version": "standard",
                    "RequestId": "req-1",
                    "Pages": [
                        json.dumps(
                            {
                                "title": "广州基地介绍",
                                "url": "https://example.com/a",
                                "passage": "广州基地是测试品牌。",
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "title": "行业观察",
                                "url": "https://example.com/b",
                                "content": "<b>广州基地</b> 在搜索中被提及。",
                            },
                            ensure_ascii=False,
                        ),
                    ],
                }
            }
        )
    )
    payload = _adapter(client).collect(SimpleNamespace(question_version_id="q-1"))  # type: ignore[arg-type]

    assert isinstance(payload, AnswerPayload)
    assert "广州基地介绍" in payload.text
    assert "广州基地是测试品牌" in payload.text
    assert "行业观察" in payload.text
    assert payload.engine_model == "yuanbao-search"
    assert payload.model_version == "standard"
    assert [item.url for item in payload.citations] == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    call = client.calls[0]
    assert call["url"] == "https://wsa.tencentcloudapi.com"
    assert call["headers"]["X-TC-Action"] == "SearchPro"
    body = json.loads(call["content"].decode("utf-8"))
    assert body == {"Query": "广州基地在生成式搜索里的表现如何？", "Cnt": 10}


def test_collect_maps_rate_limit_error() -> None:
    client = _FakeClient(
        _FakeResponse(
            {
                "Response": {
                    "Error": {
                        "Code": "RequestLimitExceeded",
                        "Message": "请求的次数超过了频率限制",
                    }
                }
            }
        )
    )
    with pytest.raises(RateLimitedFailure):
        _adapter(client).collect(SimpleNamespace(question_version_id="q-1"))  # type: ignore[arg-type]


def test_build_yuanbao_adapter_requires_secret_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YUANBAO_SECRET_ID", raising=False)
    monkeypatch.delenv(SECRET_KEY_ENV, raising=False)
    with pytest.raises(AccessBlockedFailure):
        build_yuanbao_adapter(_DummyDB(), credential_ref="YUANBAO_SECRET_ID")  # type: ignore[arg-type]

    monkeypatch.setenv("YUANBAO_SECRET_ID", "AKIDEXAMPLE")
    with pytest.raises(AccessBlockedFailure):
        build_yuanbao_adapter(_DummyDB(), credential_ref="YUANBAO_SECRET_ID")  # type: ignore[arg-type]

    monkeypatch.setenv(SECRET_KEY_ENV, "SECRETEXAMPLE")
    adapter = build_yuanbao_adapter(
        _DummyDB(),  # type: ignore[arg-type]
        credential_ref="YUANBAO_SECRET_ID",
        client=_FakeClient(_FakeResponse({"Response": {}})),  # type: ignore[arg-type]
    )
    assert adapter.endpoint == "https://wsa.tencentcloudapi.com"
    adapter.close()
