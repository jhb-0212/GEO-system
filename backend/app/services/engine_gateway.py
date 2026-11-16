"""轻量引擎网关 v2：统一结果、策略重试、fallback、耗时/token/费用与 trace 留痕。

边界：
- 不新建独立代理服务，也不接 litellm 整套平台；只在进程内包一层适配器；
- 重试分两层：网关内只重试适配器明确标记 `retryable` 的失败，Celery 仍负责任务级重试；
- 限流仍由 `EngineRateLimiter` 控制，超时由适配器 `httpx` 客户端控制；
- fallback 只在调用方显式传入备用适配器时启用；没有第二个可用入口时保持单入口失败，
  不伪造降级成功；
- 不保存 Authorization，只保存可回放的请求体（model/messages/参数）。
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from time import perf_counter, sleep
from typing import Any

from app.models import MonitoringTask
from app.services.monitoring_extraction import AnswerPayload

GATEWAY_VERSION = "engine_gateway_v2"


class EngineGateway:
    """包一层 `AnswerAdapter`，把调用结果和排障元数据一起返回。"""

    def __init__(
        self,
        adapter: Any,
        *,
        input_price_cny_per_million: Decimal | float | str | None = None,
        output_price_cny_per_million: Decimal | float | str | None = None,
    ) -> None:
        self._adapter = adapter
        self._input_price = _as_decimal(input_price_cny_per_million)
        self._output_price = _as_decimal(output_price_cny_per_million)

    def collect(
        self,
        task: MonitoringTask,
        *,
        trace_id: str | None = None,
        request_payload: dict[str, Any] | None = None,
        fallback_adapters: list[Any] | None = None,
        max_attempts: int = 1,
        retry_backoff_seconds: float = 0.0,
    ) -> AnswerPayload:
        """按适配器顺序调用；同一适配器只对 retryable 失败重试。

        `fallback_adapters` 是调用方显式准备的第二入口；不传就保持单入口语义。
        回放传入留存请求体时，备用适配器通常不适用，调用方不应同时传 fallback。
        """
        adapters = [self._adapter, *(fallback_adapters or [])]
        attempts_total = 0
        last_exc: Exception | None = None
        primary_name = _adapter_name(adapters[0])

        for adapter_index, adapter in enumerate(adapters):
            for attempt_no in range(1, max(1, int(max_attempts)) + 1):
                attempts_total += 1
                started = perf_counter()
                try:
                    if request_payload is not None and hasattr(adapter, "collect_with_request"):
                        payload = adapter.collect_with_request(task, request_payload)
                    else:
                        payload = adapter.collect(task)
                except Exception as exc:
                    # 失败也留耗时和请求体，排障页才能回答“卡在哪一步”。
                    setattr(exc, "latency_ms", _elapsed_ms(started))
                    setattr(
                        exc,
                        "request_payload",
                        getattr(adapter, "last_request_payload", None) or request_payload,
                    )
                    setattr(exc, "trace_id", trace_id)
                    setattr(exc, "gateway_attempts", attempts_total)
                    last_exc = exc
                    retryable = bool(getattr(exc, "retryable", False))
                    if attempt_no < max_attempts and retryable:
                        if retry_backoff_seconds > 0:
                            sleep(retry_backoff_seconds * attempt_no)
                        continue
                    break

                payload.trace_id = trace_id
                payload.request_payload = getattr(adapter, "last_request_payload", None) or request_payload
                payload.latency_ms = _elapsed_ms(started)
                payload.gateway_version = GATEWAY_VERSION
                payload.gateway_attempts = attempts_total
                payload.gateway_fallback_from = primary_name if adapter_index > 0 else None

                usage = _usage(payload.raw_response)
                payload.prompt_tokens = _as_int(usage.get("prompt_tokens"))
                payload.completion_tokens = _as_int(usage.get("completion_tokens"))
                payload.total_tokens = _as_int(usage.get("total_tokens"))
                if payload.total_tokens is None and (
                    payload.prompt_tokens is not None or payload.completion_tokens is not None
                ):
                    payload.total_tokens = (payload.prompt_tokens or 0) + (payload.completion_tokens or 0)

                payload.estimated_cost_cny = self._estimate_cost(
                    payload.prompt_tokens,
                    payload.completion_tokens,
                )
                return payload

        assert last_exc is not None
        setattr(last_exc, "gateway_attempts", attempts_total)
        raise last_exc

    def _estimate_cost(self, prompt_tokens: int | None, completion_tokens: int | None) -> Decimal | None:
        if self._input_price is None and self._output_price is None:
            return None
        prompt_cost = (
            Decimal(prompt_tokens or 0) * (self._input_price or Decimal(0)) / Decimal(1_000_000)
        )
        completion_cost = (
            Decimal(completion_tokens or 0) * (self._output_price or Decimal(0)) / Decimal(1_000_000)
        )
        return (prompt_cost + completion_cost).quantize(Decimal("0.000001"))


def _elapsed_ms(started: float) -> int:
    return max(0, int(round((perf_counter() - started) * 1000)))


def _adapter_name(adapter: Any) -> str:
    model = getattr(adapter, "model", None)
    if model:
        return str(model)
    return type(adapter).__name__


def _usage(raw_response: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(raw_response, dict):
        return {}
    usage = raw_response.get("usage")
    return usage if isinstance(usage, dict) else {}


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _as_decimal(value: Decimal | float | str | None) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
