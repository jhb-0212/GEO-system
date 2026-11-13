"""AI 平台入口连通性测试服务。

只做诊断：发一条固定短探针，不创建监测样本、不保存回答正文。
密钥只从环境变量读取，`credential_ref` 只存变量名，不落库明文。
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.models import AiEngineEntry
from app.models.enums import EngineProtocol

PROBE_TEXT = "只回复：pong"
PROBE_MAX_TOKENS = 8


def _endpoint(entry: AiEngineEntry) -> str | None:
    if not entry.entry_url:
        return None
    base = entry.entry_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _credential(entry: AiEngineEntry) -> tuple[str, str | None]:
    """返回 (key, error_code)；没有 key 时允许无认证入口继续尝试。"""
    if not entry.credential_ref:
        return "", None
    value = os.getenv(entry.credential_ref, "").strip()
    if not value:
        return "", "credential_missing"
    return value, None


def test_entry_connection(
    entry: AiEngineEntry,
    *,
    client: httpx.Client | None = None,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    protocol = getattr(entry.protocol, "value", str(entry.protocol))
    checked_at = datetime.now(timezone.utc)
    base_result: dict[str, Any] = {
        "success": False,
        "protocol": protocol,
        "endpoint": _endpoint(entry),
        "model_name": entry.model_name,
        "latency_ms": None,
        "error_code": None,
        "message": "",
        "checked_at": checked_at,
    }

    if entry.protocol != EngineProtocol.OPENAI_COMPATIBLE:
        base_result["error_code"] = "unsupported_protocol"
        base_result["message"] = "该入口尚未接入 openai_compatible 适配器"
        return base_result
    endpoint = base_result["endpoint"]
    if not endpoint:
        base_result["error_code"] = "entry_url_missing"
        base_result["message"] = "入口未配置 entry_url"
        return base_result
    if not entry.model_name:
        base_result["error_code"] = "model_name_missing"
        base_result["message"] = "入口未配置 model_name"
        return base_result

    api_key, credential_error = _credential(entry)
    if credential_error:
        base_result["error_code"] = credential_error
        base_result["message"] = f"环境变量 {entry.credential_ref} 未配置"
        return base_result

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {
        "model": entry.model_name,
        "messages": [{"role": "user", "content": PROBE_TEXT}],
        "max_tokens": PROBE_MAX_TOKENS,
        "stream": False,
    }

    owned_client = client is None
    http = client or httpx.Client(timeout=timeout_seconds)
    started = time.perf_counter()
    try:
        response = http.post(endpoint, headers=headers, json=body)
        base_result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
    except httpx.TimeoutException:
        base_result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        base_result["error_code"] = "timeout"
        base_result["message"] = "连接超时"
        return base_result
    except httpx.HTTPError as exc:
        base_result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        base_result["error_code"] = "unreachable"
        base_result["message"] = f"服务不可达: {exc}"
        return base_result
    finally:
        if owned_client:
            http.close()

    status = response.status_code
    if status == 200:
        base_result["success"] = True
        base_result["message"] = "连接成功"
        return base_result
    if status in (401, 403):
        base_result["error_code"] = "auth_failed"
        base_result["message"] = f"鉴权失败（HTTP {status}）"
    elif status == 404:
        base_result["error_code"] = "endpoint_not_found"
        base_result["message"] = "接口路径不存在，检查 entry_url 是否包含正确的 /v1"
    elif status == 429:
        base_result["error_code"] = "rate_limited"
        base_result["message"] = "触发平台限流（HTTP 429）"
    elif status >= 500:
        base_result["error_code"] = "upstream_error"
        base_result["message"] = f"平台服务异常（HTTP {status}）"
    else:
        base_result["error_code"] = "http_error"
        base_result["message"] = f"请求被拒绝（HTTP {status}）"
    return base_result
