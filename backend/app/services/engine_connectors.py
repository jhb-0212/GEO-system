"""AI 平台入口连通性测试服务。

只做诊断：发一条固定短探针，不创建监测样本、不保存回答正文。
密钥只从环境变量读取，`credential_ref` 只存变量名，不落库明文。
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.credentials import read_credential_env
from app.models import AiEngineEntry
from app.models.enums import EngineProtocol
from app.services.doubao_search_adapter import MODEL_NOT_OPEN_CODES
from app.services.engine_credentials import (
    resolve_entry_secret,
    resolve_entry_secret_secondary,
)
from app.services.engine_url_policy import validate_engine_url

PROBE_TEXT = "只回复：pong"
PROBE_MAX_TOKENS = 8


def _uses_qianfan_model_web_search(entry: AiEngineEntry) -> bool:
    """千帆 ERNIE 对话模型的联网开关；独立 AI 搜索产品不适用。"""
    if not getattr(entry, "supports_search", False):
        return False
    parsed = urlparse(entry.entry_url or "")
    path = parsed.path.rstrip("/") or "/"
    return (
        (parsed.hostname or "").casefold() == "qianfan.baidubce.com"
        and path in {"/v2", "/v2/chat/completions"}
    )


def _doubao_error_detail(response: httpx.Response) -> tuple[str, str]:
    """从方舟错误响应里取 code/message，供探针给出可定位的提示。"""
    try:
        data = response.json()
    except ValueError:
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    error = data.get("error")
    if not isinstance(error, dict):
        return "", ""
    return str(error.get("code") or "").strip(), str(error.get("message") or "").strip()


def _endpoint(entry: AiEngineEntry) -> str | None:
    if not entry.entry_url:
        return None
    base = entry.entry_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _credential(entry: AiEngineEntry) -> tuple[str, str | None]:
    """返回 (key, error_code)；系统内填写的密钥优先，环境变量兜底。"""
    value = resolve_entry_secret(entry)
    if value:
        return value, None
    # 测试里常以轻量对象构造 entry，这里按属性存在性判断，避免硬依赖 ORM 字段
    if not getattr(entry, "credential_ref", None) and not getattr(
        entry, "encrypted_secret", None
    ):
        # 允许无认证入口继续尝试
        return "", None
    return "", "credential_missing"


def _test_wenxin_search_entry(
    entry: AiEngineEntry,
    *,
    client: httpx.Client | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    """文心/千帆 AI 搜索连通性：固定 messages 探针，校验返回有 references。"""
    from app.services.wenxin_search_adapter import (
        DEFAULT_CREDENTIAL_REF,
        DEFAULT_ENDPOINT,
    )

    endpoint = entry.entry_url or DEFAULT_ENDPOINT
    ref = (entry.credential_ref or "").strip() or DEFAULT_CREDENTIAL_REF
    result: dict[str, Any] = {
        "success": False,
        "protocol": "wenxin_search",
        "endpoint": endpoint,
        "model_name": entry.model_name or "wenxin-search",
        "latency_ms": None,
        "error_code": None,
        "message": "",
        "checked_at": datetime.now(timezone.utc),
    }
    api_key = resolve_entry_secret(entry, default_ref=ref)
    if not api_key:
        result["error_code"] = "credential_missing"
        result["message"] = f"未配置密钥（系统内填写或环境变量 {ref}）"
        return result

    body = {"messages": [{"role": "user", "content": "ping"}]}
    owned_client = client is None
    http = client or httpx.Client(timeout=timeout_seconds)
    started = time.perf_counter()
    try:
        response = http.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        )
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
    except httpx.TimeoutException:
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        result["error_code"] = "timeout"
        result["message"] = "连接超时"
        return result
    except httpx.HTTPError as exc:
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        result["error_code"] = "unreachable"
        result["message"] = f"服务不可达: {exc}"
        return result
    finally:
        if owned_client:
            http.close()

    status = response.status_code
    if status in (401, 403):
        result["error_code"] = "auth_failed"
        result["message"] = f"鉴权失败（HTTP {status}）"
        return result
    if status == 429:
        result["error_code"] = "rate_limited"
        result["message"] = "触发平台限流（HTTP 429）"
        return result
    if status >= 500:
        result["error_code"] = "upstream_error"
        result["message"] = f"平台服务异常（HTTP {status}）"
        return result
    if status != 200:
        result["error_code"] = "http_error"
        result["message"] = f"请求被拒绝（HTTP {status}）"
        return result
    try:
        data = response.json()
    except ValueError:
        result["error_code"] = "invalid_response"
        result["message"] = "返回不是合法 JSON"
        return result
    if not isinstance(data, dict) or not isinstance(data.get("references"), list):
        message = ""
        if isinstance(data, dict):
            if isinstance(data.get("error"), dict):
                message = str(data["error"].get("message") or "")
            elif data.get("error_msg"):
                message = str(data["error_msg"])
        result["error_code"] = "invalid_response"
        result["message"] = f"返回缺少 references 数组{('：' + message) if message else ''}"
        return result

    result["success"] = True
    result["message"] = f"连通正常（references {len(data['references'])} 条）"
    return result


def _test_doubao_search_entry(
    entry: AiEngineEntry,
    *,
    client: httpx.Client | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    """豆包搜索连通性：固定短探针，带 web_search 工具；只校验返回有 output 数组。"""
    from app.services.doubao_search_adapter import (
        DEFAULT_CREDENTIAL_REF,
        DEFAULT_ENDPOINT,
    )

    endpoint = entry.entry_url or DEFAULT_ENDPOINT
    ref = (entry.credential_ref or "").strip() or DEFAULT_CREDENTIAL_REF
    result: dict[str, Any] = {
        "success": False,
        "protocol": "doubao_search",
        "endpoint": endpoint,
        "model_name": entry.model_name or "",
        "latency_ms": None,
        "error_code": None,
        "message": "",
        "checked_at": datetime.now(timezone.utc),
    }
    if not entry.model_name:
        result["error_code"] = "model_name_missing"
        result["message"] = "入口未配置 model_name（方舟模型 ID，如 doubao-seed-2-1-pro-260915）"
        return result
    api_key = resolve_entry_secret(entry, default_ref=ref)
    if not api_key:
        result["error_code"] = "credential_missing"
        result["message"] = f"未配置密钥（系统内填写或环境变量 {ref}）"
        return result

    body = {
        "model": entry.model_name,
        "tools": [{"type": "web_search"}],
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "ping"}],
            }
        ],
        "max_output_tokens": 64,
        "stream": False,
    }
    owned_client = client is None
    http = client or httpx.Client(timeout=timeout_seconds)
    started = time.perf_counter()
    try:
        response = http.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        )
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
    except httpx.TimeoutException:
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        result["error_code"] = "timeout"
        result["message"] = "连接超时"
        return result
    except httpx.HTTPError as exc:
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        result["error_code"] = "unreachable"
        result["message"] = f"服务不可达: {exc}"
        return result
    finally:
        if owned_client:
            http.close()

    status = response.status_code
    if status in (401, 403):
        denied_code, denied_message = _doubao_error_detail(response)
        if denied_code == "AccessDenied" and "web search" in denied_message.lower():
            result["error_code"] = "search_not_open"
            result["message"] = (
                f"联网搜索未开通（{denied_code}）：{denied_message}；"
                "请到火山方舟控制台确认联网搜索的激活状态后重试"
            )
            return result
        result["error_code"] = "auth_failed"
        result["message"] = f"鉴权失败（HTTP {status}）"
        return result
    if status == 429:
        result["error_code"] = "rate_limited"
        result["message"] = "触发平台限流（HTTP 429）"
        return result
    if status >= 500:
        result["error_code"] = "upstream_error"
        result["message"] = f"平台服务异常（HTTP {status}）"
        return result
    if status != 200:
        error_code, error_message = _doubao_error_detail(response)
        if error_code in MODEL_NOT_OPEN_CODES:
            result["error_code"] = "model_not_open"
            result["message"] = (
                f"模型未开通（{error_code}）：{error_message}；"
                "请到火山方舟控制台开通该模型服务后重试"
            )
            return result
        detail = " ".join(part for part in (error_code, error_message) if part)
        result["error_code"] = "http_error"
        result["message"] = f"请求被拒绝（HTTP {status}）{(' ' + detail) if detail else ''}"
        return result
    try:
        data = response.json()
    except ValueError:
        result["error_code"] = "invalid_response"
        result["message"] = "返回不是合法 JSON"
        return result
    if not isinstance(data, dict) or not isinstance(data.get("output"), list):
        message = ""
        if isinstance(data, dict) and isinstance(data.get("error"), dict):
            message = str(data["error"].get("message") or "")
        result["error_code"] = "invalid_response"
        result["message"] = f"返回缺少 output 数组{('：' + message) if message else ''}"
        return result

    result["success"] = True
    result["message"] = f"连通正常（output {len(data['output'])} 项）"
    return result


def _test_deepseek_web_search_entry(
    entry: AiEngineEntry,
    *,
    client: httpx.Client | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    """DeepSeek 服务端联网搜索：声明 deepseek_web_search 发一条短探针，校验 output 里能出回答。"""
    from app.services.deepseek_web_search_adapter import (
        DEFAULT_CREDENTIAL_REF,
        DEFAULT_ENDPOINT,
        DEFAULT_MODEL,
    )

    endpoint = entry.entry_url or DEFAULT_ENDPOINT
    ref = (entry.credential_ref or "").strip() or DEFAULT_CREDENTIAL_REF
    model = (entry.model_name or "").strip() or DEFAULT_MODEL
    result: dict[str, Any] = {
        "success": False,
        "protocol": "deepseek_web_search",
        "endpoint": endpoint,
        "model_name": model,
        "latency_ms": None,
        "error_code": None,
        "message": "",
        "checked_at": datetime.now(timezone.utc),
    }
    api_key = resolve_entry_secret(entry, default_ref=ref)
    if not api_key:
        result["error_code"] = "credential_missing"
        result["message"] = f"未配置密钥（系统内填写或环境变量 {ref}）"
        return result

    body = {
        "model": model,
        "tools": [{"type": "deepseek_web_search"}],
        "input": "ping",
        "max_output_tokens": 64,
        "stream": False,
    }
    owned_client = client is None
    http = client or httpx.Client(timeout=timeout_seconds)
    started = time.perf_counter()
    try:
        response = http.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        )
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
    except httpx.TimeoutException:
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        result["error_code"] = "timeout"
        result["message"] = "连接超时"
        return result
    except httpx.HTTPError as exc:
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        result["error_code"] = "unreachable"
        result["message"] = f"服务不可达: {exc}"
        return result
    finally:
        if owned_client:
            http.close()

    status = response.status_code
    if status in (401, 402, 403):
        result["error_code"] = "auth_failed"
        result["message"] = f"鉴权失败（HTTP {status}）"
        return result
    if status == 429:
        result["error_code"] = "rate_limited"
        result["message"] = "触发平台限流（HTTP 429）"
        return result
    if status >= 500:
        result["error_code"] = "upstream_error"
        result["message"] = f"平台服务异常（HTTP {status}）"
        return result
    if status != 200:
        result["error_code"] = "http_error"
        result["message"] = f"请求被拒绝（HTTP {status}）"
        return result
    try:
        data = response.json()
    except ValueError:
        result["error_code"] = "invalid_response"
        result["message"] = "返回不是合法 JSON"
        return result
    if not isinstance(data, dict) or not isinstance(data.get("output"), list):
        result["error_code"] = "invalid_response"
        result["message"] = "返回缺少 output 数组"
        return result

    text = ""
    for item in data["output"]:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for block in item.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "output_text":
                text += str(block.get("text") or "")
    if not text.strip():
        result["error_code"] = "invalid_response"
        result["message"] = "output 里没有 output_text 回答"
        return result

    result["success"] = True
    result["message"] = f"连通正常（output {len(data['output'])} 项，回答 {len(text)} 字）"
    return result


def _test_yuanbao_entry(
    entry: AiEngineEntry,
    *,
    client: httpx.Client | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    from app.services.yuanbao_search_adapter import (
        DEFAULT_ACTION,
        DEFAULT_ENDPOINT,
        DEFAULT_VERSION,
        SECRET_KEY_ENV,
        build_tc3_headers,
    )

    endpoint = entry.entry_url or DEFAULT_ENDPOINT
    checked_at = datetime.now(timezone.utc)
    result: dict[str, Any] = {
        "success": False,
        "protocol": "yuanbao_search",
        "endpoint": endpoint,
        "model_name": entry.model_name or "yuanbao-search",
        "latency_ms": None,
        "error_code": None,
        "message": "",
        "checked_at": checked_at,
    }
    if not entry.credential_ref and not entry.encrypted_secret:
        result["error_code"] = "credential_missing"
        result["message"] = "入口未配置密钥（系统内填写 SecretId 或 credential_ref 环境变量名）"
        return result
    secret_id = resolve_entry_secret(entry)
    secret_key = resolve_entry_secret_secondary(entry, default_ref=SECRET_KEY_ENV)
    if not secret_id:
        result["error_code"] = "credential_missing"
        result["message"] = f"未配置 SecretId（系统内填写或环境变量 {entry.credential_ref or '—'}）"
        return result
    if not secret_key:
        result["error_code"] = "credential_missing"
        result["message"] = f"未配置 SecretKey（系统内填写或环境变量 {SECRET_KEY_ENV}）"
        return result

    body = b'{"Query":"ping"}'
    headers = build_tc3_headers(
        secret_id=secret_id,
        secret_key=secret_key,
        action=DEFAULT_ACTION,
        version=DEFAULT_VERSION,
        endpoint=endpoint,
        body=body,
    )
    owned_client = client is None
    http = client or httpx.Client(timeout=timeout_seconds)
    started = time.perf_counter()
    try:
        response = http.post(endpoint, headers=headers, content=body)
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
    except httpx.TimeoutException:
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        result["error_code"] = "timeout"
        result["message"] = "连接超时"
        return result
    except httpx.HTTPError as exc:
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        result["error_code"] = "unreachable"
        result["message"] = f"服务不可达: {exc}"
        return result
    finally:
        if owned_client:
            http.close()

    status = response.status_code
    if status in (401, 403):
        result["error_code"] = "auth_failed"
        result["message"] = f"鉴权失败（HTTP {status}）"
        return result
    if status == 429:
        result["error_code"] = "rate_limited"
        result["message"] = "触发平台限流（HTTP 429）"
        return result
    if status >= 500:
        result["error_code"] = "upstream_error"
        result["message"] = f"平台服务异常（HTTP {status}）"
        return result
    if status != 200:
        result["error_code"] = "http_error"
        result["message"] = f"请求被拒绝（HTTP {status}）"
        return result
    try:
        data = response.json()
    except ValueError:
        result["error_code"] = "invalid_response"
        result["message"] = "返回不是合法 JSON"
        return result
    payload = data.get("Response") if isinstance(data, dict) else None
    error = payload.get("Error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        result["error_code"] = str(error.get("Code") or "upstream_error")
        result["message"] = str(error.get("Message") or "元宝搜索返回错误")
        return result
    result["success"] = True
    result["message"] = "连接成功"
    return result


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

    # 凭据发送前先校验目标地址：非法入口直接失败，不进入任何 header/TC3 签名分支。
    try:
        validate_engine_url(entry.entry_url, entry.protocol)
    except ValueError as exc:
        base_result["error_code"] = "entry_url_invalid"
        base_result["message"] = str(exc)
        return base_result

    if entry.protocol == EngineProtocol.YUANBAO_SEARCH:
        return _test_yuanbao_entry(entry, client=client, timeout_seconds=timeout_seconds)
    if entry.protocol == EngineProtocol.WENXIN_SEARCH:
        return _test_wenxin_search_entry(
            entry, client=client, timeout_seconds=timeout_seconds
        )
    if entry.protocol == EngineProtocol.DOUBAO_SEARCH:
        return _test_doubao_search_entry(
            entry, client=client, timeout_seconds=timeout_seconds
        )
    if entry.protocol == EngineProtocol.DEEPSEEK_WEB_SEARCH:
        return _test_deepseek_web_search_entry(
            entry, client=client, timeout_seconds=timeout_seconds
        )
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
    if _uses_qianfan_model_web_search(entry):
        body["web_search"] = {"enable": True}

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
