"""轻量引擎网关：统一结果、耗时、token/费用、原始请求与 trace 留痕。

边界：
- 不新建独立代理服务，也不接 litellm 整套平台；只在进程内包一层适配器；
- 重试仍由 Celery 任务级控制，限流仍由 `EngineRateLimiter` 控制，超时由适配器
  `httpx` 客户端控制；网关只负责把这些执行结果归一并留痕；
- fallback 需要同一问题的第二个可用入口，当前只有 DeepSeek 单入口，暂不伪造降级；
- 不保存 Authorization，只保存可回放的请求体（model/messages/参数）。
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from time import perf_counter
from typing import Any

from app.models import MonitoringTask
from app.services.monitoring_extraction import AnswerPayload

GATEWAY_VERSION = "engine_gateway_v1"


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
    ) -> AnswerPayload:
        started = perf_counter()
        try:
            if request_payload is not None and hasattr(self._adapter, "collect_with_request"):
                payload = self._adapter.collect_with_request(task, request_payload)
            else:
                payload = self._adapter.collect(task)
        except Exception as exc:
            # 失败也留耗时和请求体，排障页才能回答“卡在哪一步”。
            setattr(exc, "latency_ms", _elapsed_ms(started))
            setattr(
                exc,
                "request_payload",
                getattr(self._adapter, "last_request_payload", None) or request_payload,
            )
            setattr(exc, "trace_id", trace_id)
            raise

        payload.trace_id = trace_id
        payload.request_payload = getattr(self._adapter, "last_request_payload", None) or request_payload
        payload.latency_ms = _elapsed_ms(started)
        payload.gateway_version = GATEWAY_VERSION

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
