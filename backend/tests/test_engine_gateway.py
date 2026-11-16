"""引擎网关统一结果与留痕测试。"""

from decimal import Decimal

import pytest

from app.services.engine_gateway import GATEWAY_VERSION, EngineGateway
from app.services.monitoring_collection import (
    AccessBlockedFailure,
    CollectionFailure,
    RateLimitedFailure,
)
from app.services.monitoring_extraction import AnswerPayload


class StubAdapter:
    def __init__(self, payload: AnswerPayload | None = None, exc: Exception | None = None):
        self.payload = payload
        self.exc = exc
        self.calls = 0
        self.last_request_payload = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "测试"}],
        }

    def collect(self, _task):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return self.payload


def test_gateway_records_trace_latency_tokens_and_cost():
    payload = AnswerPayload(
        text="回答",
        raw_response={"usage": {"prompt_tokens": 10, "completion_tokens": 5}},
    )
    gateway = EngineGateway(
        StubAdapter(payload),
        input_price_cny_per_million=Decimal("2"),
        output_price_cny_per_million=Decimal("0.5"),
    )
    result = gateway.collect(object(), trace_id="trace-1")

    assert result.trace_id == "trace-1"
    assert result.request_payload["model"] == "deepseek-chat"
    assert result.latency_ms is not None and result.latency_ms >= 0
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5
    assert result.total_tokens == 15
    assert abs(result.estimated_cost_cny - Decimal("0.0000225")) <= Decimal("0.0000005")
    assert result.gateway_version == GATEWAY_VERSION


def test_gateway_keeps_cost_empty_without_price():
    result = EngineGateway(
        StubAdapter(AnswerPayload(raw_response={"usage": {"total_tokens": 8}}))
    ).collect(object(), trace_id="trace-2")
    assert result.total_tokens == 8
    assert result.estimated_cost_cny is None


def test_gateway_attaches_request_and_latency_on_failure():
    gateway = EngineGateway(StubAdapter(exc=RateLimitedFailure("429")))
    with pytest.raises(CollectionFailure) as caught:
        gateway.collect(object(), trace_id="trace-3")
    failure = caught.value
    assert getattr(failure, "trace_id") == "trace-3"
    assert getattr(failure, "request_payload")["model"] == "deepseek-chat"
    assert getattr(failure, "latency_ms") is not None


def test_gateway_retries_retryable_failures():
    failing = StubAdapter(exc=RateLimitedFailure("429"))
    gateway = EngineGateway(failing)
    with pytest.raises(CollectionFailure):
        gateway.collect(object(), trace_id="trace-4", max_attempts=2)
    assert failing.calls == 2


def test_gateway_does_not_retry_non_retryable_failures():
    failing = StubAdapter(exc=AccessBlockedFailure("401"))
    gateway = EngineGateway(failing)
    with pytest.raises(CollectionFailure):
        gateway.collect(object(), trace_id="trace-5", max_attempts=2)
    assert failing.calls == 1


def test_gateway_falls_back_to_second_adapter():
    primary = StubAdapter(exc=AccessBlockedFailure("401"))
    fallback = StubAdapter(AnswerPayload(text="备用回答"))
    gateway = EngineGateway(primary)
    result = gateway.collect(object(), trace_id="trace-6", fallback_adapters=[fallback])
    assert result.text == "备用回答"
    assert result.gateway_attempts == 2
    assert result.gateway_fallback_from == "StubAdapter"
    assert primary.calls == 1
    assert fallback.calls == 1
