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
from app.services.engine_web_search import (
    ZHIPU_SEARCH_CONTENT_SIZE,
    ZHIPU_SEARCH_COUNT,
    ZHIPU_SEARCH_ENGINE,
    is_kimi_web_search_entry,
    is_metaso_web_search_entry,
    is_qianfan_model_web_search_entry,
    is_qihu360_ai_search_entry,
    is_qwen_web_search_entry,
    is_spark_maas_entry,
    is_zhipu_web_search_entry,
)

PROBE_TEXT = "只回复：pong"
PROBE_MAX_TOKENS = 8


def _uses_qianfan_model_web_search(entry: AiEngineEntry) -> bool:
    """兼容旧调用名：千帆 ERNIE 对话模型是否打开联网开关。"""
    return is_qianfan_model_web_search_entry(entry)


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
        # DashScope 等平台把 code/message 放在顶层，不一定有 error 包装。
        return str(data.get("code") or "").strip(), str(data.get("message") or "").strip()
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


def _test_kimi_web_search_entry(
    entry: AiEngineEntry,
    *,
    client: httpx.Client | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Kimi Responses 联网探针：声明 web_search，校验 output 数组。"""
    from app.services.kimi_web_search_adapter import (
        DEFAULT_CREDENTIAL_REF,
        DEFAULT_ENDPOINT,
        DEFAULT_MODEL,
        REASONING_EFFORT,
    )

    endpoint = (entry.entry_url or "").strip() or DEFAULT_ENDPOINT
    if not endpoint.rstrip("/").endswith("/responses"):
        endpoint = f"{endpoint.rstrip('/')}/responses"
    ref = (entry.credential_ref or "").strip() or DEFAULT_CREDENTIAL_REF
    model = (entry.model_name or "").strip() or DEFAULT_MODEL
    result: dict[str, Any] = {
        "success": False,
        "protocol": "openai_compatible",
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
        "input": "联网搜索测试：今天有什么新闻？",
        "tools": [{"type": "web_search"}],
        "include": ["web_search_call.action.sources"],
        "max_output_tokens": 512,
        "reasoning_effort": REASONING_EFFORT,
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


def _test_qwen_web_search_entry(
    entry: AiEngineEntry,
    *,
    client: httpx.Client | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    """千问 Responses 联网探针：声明 web_search，校验 output 与来源数量。"""
    from app.services.qwen_web_search_adapter import (
        DEFAULT_CREDENTIAL_REF,
        DEFAULT_ENDPOINT,
        DEFAULT_MODEL,
        MAX_OUTPUT_TOKENS,
    )

    endpoint = (entry.entry_url or "").strip() or DEFAULT_ENDPOINT
    if not endpoint.rstrip("/").endswith("/responses"):
        endpoint = f"{endpoint.rstrip('/')}/responses"
    ref = (entry.credential_ref or "").strip() or DEFAULT_CREDENTIAL_REF
    model = (entry.model_name or "").strip() or DEFAULT_MODEL
    result: dict[str, Any] = {
        "success": False,
        "protocol": "openai_compatible",
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
        "instructions": "请使用联网搜索工具检索最新网页信息后再回答。",
        "input": "联网搜索测试：今天广州有哪些人工智能相关新闻？",
        "tools": [{"type": "web_search"}],
        "max_output_tokens": MAX_OUTPUT_TOKENS,
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

    text = ""
    source_urls: set[str] = set()
    for item in data["output"]:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message":
            for block in item.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "output_text":
                    text += str(block.get("text") or "")
        if item.get("type") == "web_search_call":
            action = item.get("action")
            if isinstance(action, dict):
                for source in action.get("sources") or []:
                    if isinstance(source, dict):
                        url = str(source.get("url") or "").strip()
                        if url:
                            source_urls.add(url)
    if not text.strip():
        status_text = str(data.get("status") or "").strip()
        result["error_code"] = "invalid_response"
        result["message"] = f"output 里没有 output_text 回答（状态 {status_text or '未知'}）"
        return result

    result["success"] = True
    result["message"] = (
        f"连通正常（output {len(data['output'])} 项，回答 {len(text)} 字，"
        f"来源 {len(source_urls)} 条）"
    )
    return result


def _test_qihu360_ai_search_entry(
    entry: AiEngineEntry,
    *,
    client: httpx.Client | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    """360 智脑 AI 搜索探针：校验 choices 文本与 references 数量。"""
    from app.services.qihu360_search_adapter import (
        DEFAULT_CREDENTIAL_REF,
        DEFAULT_ENDPOINT,
        DEFAULT_MODEL,
        _citations,
        _extract_text,
        build_request_body,
        normalize_endpoint,
    )

    endpoint = normalize_endpoint(entry.entry_url or DEFAULT_ENDPOINT)
    ref = (entry.credential_ref or "").strip() or DEFAULT_CREDENTIAL_REF
    model = (entry.model_name or "").strip() or DEFAULT_MODEL
    result: dict[str, Any] = {
        "success": False,
        "protocol": "openai_compatible",
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

    body = build_request_body(
        "联网搜索测试：今天广州有哪些人工智能相关新闻？",
        model,
    )
    body["max_refer_search_items"] = 10
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
        error_code, error_message = _doubao_error_detail(response)
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
    if not isinstance(data, dict):
        result["error_code"] = "invalid_response"
        result["message"] = "返回结构不是 JSON 对象"
        return result

    response_code = ""
    for key in ("code", "errno"):
        value = data.get(key)
        if value not in (None, 0, "0", ""):
            response_code = str(value)
            break
    if response_code:
        result["error_code"] = "invalid_response"
        result["message"] = (
            f"平台返回错误码 {response_code}：{str(data.get('message') or '').strip()}"
        )
        return result

    if not isinstance(data.get("choices"), list):
        result["error_code"] = "invalid_response"
        result["message"] = "返回缺少 choices 数组"
        return result
    text = _extract_text(data)
    if not text.strip():
        result["error_code"] = "invalid_response"
        result["message"] = "choices 里没有可用回答文本"
        return result

    citations = _citations(data)
    result["success"] = True
    result["message"] = (
        f"连通正常（回答 {len(text)} 字，references {len(citations)} 条）"
    )
    return result


def _test_zhipu_web_search_entry(
    entry: AiEngineEntry,
    *,
    client: httpx.Client | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    """智谱 GLM 联网探针：独立 Web Search API 取来源，再用入口配置的模型回答。

    不在探针里绑定具体模型；`model_name` 配什么，就用什么发 Chat Completions。
    """
    endpoint = _endpoint(entry) or "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    api_base = (
        endpoint[: -len("/chat/completions")]
        if endpoint.endswith("/chat/completions")
        else endpoint.rstrip("/")
    )
    search_endpoint = f"{api_base}/web_search"
    ref = (entry.credential_ref or "").strip() or "ZHIPU_API_KEY"
    model = (entry.model_name or "").strip()
    result: dict[str, Any] = {
        "success": False,
        "protocol": "openai_compatible",
        "endpoint": endpoint,
        "model_name": model or None,
        "latency_ms": None,
        "error_code": None,
        "message": "",
        "checked_at": datetime.now(timezone.utc),
    }
    if not model:
        result["error_code"] = "model_name_missing"
        result["message"] = "智谱入口未配置 model_name；模型由入口配置决定，不在代码里锁定"
        return result
    api_key = resolve_entry_secret(entry, default_ref=ref)
    if not api_key:
        result["error_code"] = "credential_missing"
        result["message"] = f"未配置密钥（系统内填写或环境变量 {ref}）"
        return result

    question = "今天广州有哪些人工智能相关新闻？"
    search_body = {
        "search_query": question,
        "search_engine": ZHIPU_SEARCH_ENGINE,
        "search_intent": False,
        "count": 5,
        "search_recency_filter": "noLimit",
        "content_size": "medium",
    }
    chat_body: dict[str, Any] = {}
    owned_client = client is None
    http = client or httpx.Client(timeout=timeout_seconds)
    started = time.perf_counter()
    try:
        search_response = http.post(
            search_endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            content=json.dumps(search_body, ensure_ascii=False).encode("utf-8"),
        )
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        status = search_response.status_code
        if status in (401, 402, 403):
            _code, detail = _doubao_error_detail(search_response)
            result["error_code"] = "auth_failed"
            result["message"] = f"联网搜索鉴权失败（HTTP {status}）{(' ' + detail) if detail else ''}"
            return result
        if status == 429:
            code, detail = _doubao_error_detail(search_response)
            if code == "1113" or "余额不足" in detail or "资源包" in detail:
                result["error_code"] = "insufficient_balance"
                result["message"] = (
                    f"智谱搜索余额不足或无可用资源包（{code or '429'}）："
                    f"{detail or '请充值'}；充值后重试"
                )
                return result
            result["error_code"] = "rate_limited"
            result["message"] = "智谱联网搜索触发限流（HTTP 429）"
            return result
        if status >= 500:
            result["error_code"] = "upstream_error"
            result["message"] = f"智谱联网搜索服务异常（HTTP {status}）"
            return result
        if status != 200:
            code, detail = _doubao_error_detail(search_response)
            joined = " ".join(part for part in (code, detail) if part)
            result["error_code"] = "http_error"
            result["message"] = (
                f"智谱联网搜索被拒绝（HTTP {status}）"
                f"{(' ' + joined) if joined else ''}"
            )
            return result
        try:
            search_data = search_response.json()
        except ValueError:
            result["error_code"] = "invalid_response"
            result["message"] = "联网搜索返回不是合法 JSON"
            return result
        if not isinstance(search_data, dict):
            result["error_code"] = "invalid_response"
            result["message"] = "联网搜索返回结构不是 JSON 对象"
            return result
        error = search_data.get("error")
        if isinstance(error, dict):
            code = str(error.get("code") or "")
            detail = str(error.get("message") or "").strip()
            if code == "1113" or "余额不足" in detail or "资源包" in detail:
                result["error_code"] = "insufficient_balance"
                result["message"] = (
                    f"智谱搜索余额不足或无可用资源包（{code or '1113'}）："
                    f"{detail or '请充值'}；充值后重试"
                )
                return result
            result["error_code"] = "upstream_error"
            result["message"] = f"智谱搜索业务错误 {code or 'unknown'}：{detail}"
            return result

        sources = search_data.get("search_result")
        if not isinstance(sources, list) or not sources:
            result["error_code"] = "invalid_response"
            result["message"] = "智谱联网搜索没有返回 search_result 来源"
            return result
        source_urls: set[str] = set()
        source_lines: list[str] = []
        for index, item in enumerate(sources[:5], 1):
            if not isinstance(item, dict):
                continue
            link = str(item.get("link") or "").strip()
            if link:
                source_urls.add(link)
            title = str(item.get("title") or "").strip() or "无标题"
            content = str(item.get("content") or "").strip()
            source_lines.append(f"[ref_{index}] {title} {link}\n{content[:200]}")
        if not source_urls:
            result["error_code"] = "invalid_response"
            result["message"] = "智谱联网搜索返回的来源缺少可审计 URL"
            return result

        chat_body = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是中文问答助手。请只依据下面的搜索结果回答，"
                        "不要编造资料中没有的链接或事实。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"问题：{question}\n\n搜索结果：\n"
                        + "\n".join(source_lines)
                    ),
                },
            ],
            "temperature": 0.2,
            "max_tokens": 512,
            "stream": False,
        }
        chat_response = http.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            content=json.dumps(chat_body, ensure_ascii=False).encode("utf-8"),
        )
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        status = chat_response.status_code
        if status in (401, 402, 403):
            _code, detail = _doubao_error_detail(chat_response)
            result["error_code"] = "auth_failed"
            result["message"] = f"模型回答鉴权失败（HTTP {status}）{(' ' + detail) if detail else ''}"
            return result
        if status == 429:
            code, detail = _doubao_error_detail(chat_response)
            if code == "1113" or "余额不足" in detail or "资源包" in detail:
                result["error_code"] = "insufficient_balance"
                result["message"] = (
                    f"搜索成功（来源 {len(source_urls)} 条），但模型回答余额不足或无可用资源包"
                    f"（{code or '429'}）：{detail or '请充值'}；充值后重试"
                )
                return result
            result["error_code"] = "rate_limited"
            result["message"] = "模型回答触发平台限流（HTTP 429）"
            return result
        if status >= 500:
            result["error_code"] = "upstream_error"
            result["message"] = f"模型回答服务异常（HTTP {status}）"
            return result
        if status != 200:
            code, detail = _doubao_error_detail(chat_response)
            joined = " ".join(part for part in (code, detail) if part)
            result["error_code"] = "http_error"
            result["message"] = (
                f"模型回答被拒绝（HTTP {status}）"
                f"{(' ' + joined) if joined else ''}"
            )
            return result
        try:
            chat_data = chat_response.json()
        except ValueError:
            result["error_code"] = "invalid_response"
            result["message"] = "模型回答返回不是合法 JSON"
            return result
        if not isinstance(chat_data, dict):
            result["error_code"] = "invalid_response"
            result["message"] = "模型回答返回结构不是 JSON 对象"
            return result
        error = chat_data.get("error")
        if isinstance(error, dict):
            result["error_code"] = "upstream_error"
            result["message"] = (
                f"模型回答业务错误 {error.get('code') or 'unknown'}："
                f"{str(error.get('message') or '').strip()}"
            )
            return result
        choices = chat_data.get("choices")
        if not isinstance(choices, list) or not choices:
            result["error_code"] = "invalid_response"
            result["message"] = "模型回答返回缺少 choices"
            return result
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first.get("message"), dict) else {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            result["error_code"] = "invalid_response"
            result["message"] = "模型回答返回没有可用文本"
            return result

        result["success"] = True
        result["message"] = (
            f"连接成功（回答 {len(content.strip())} 字，来源 {len(source_urls)} 条）"
        )
        return result
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


def _spark_error_detail(response: httpx.Response) -> tuple[Any, str]:
    """解析星辰错误体：兼容 OpenAI 风格 `error{code,message}` 与顶层 `code`。"""
    try:
        data = response.json()
    except ValueError:
        return None, ""
    if not isinstance(data, dict):
        return None, ""
    error = data.get("error")
    if isinstance(error, dict):
        return error.get("code"), str(error.get("message") or "").strip()
    return data.get("code"), str(data.get("message") or "").strip()


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
    if entry.protocol == EngineProtocol.OPENAI_COMPATIBLE and is_kimi_web_search_entry(entry):
        return _test_kimi_web_search_entry(
            entry, client=client, timeout_seconds=timeout_seconds
        )
    if entry.protocol == EngineProtocol.OPENAI_COMPATIBLE and is_qwen_web_search_entry(entry):
        # 千问 Responses 的 16000 输出预算包含思考，联网探针可能超过默认 30s。
        return _test_qwen_web_search_entry(
            entry,
            client=client,
            timeout_seconds=max(timeout_seconds, 120.0),
        )
    if entry.protocol == EngineProtocol.OPENAI_COMPATIBLE and is_qihu360_ai_search_entry(entry):
        return _test_qihu360_ai_search_entry(
            entry,
            client=client,
            timeout_seconds=max(timeout_seconds, 120.0),
        )
    if entry.protocol == EngineProtocol.OPENAI_COMPATIBLE and is_zhipu_web_search_entry(entry):
        return _test_zhipu_web_search_entry(
            entry,
            client=client,
            timeout_seconds=max(timeout_seconds, 120.0),
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
    if is_spark_maas_entry(entry):
        body = {
            "model": entry.model_name,
            "messages": [{"role": "user", "content": PROBE_TEXT}],
            "max_completion_tokens": PROBE_MAX_TOKENS,
            "thinking": {"type": "disabled"},
            "stream": False,
        }
        if entry.supports_search:
            body["tools"] = [
                {
                    "type": "web_search",
                    "web_search": {"enable": True},
                }
            ]
            body["tool_choice"] = "auto"
    elif _uses_qianfan_model_web_search(entry):
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
        if is_spark_maas_entry(entry):
            try:
                data = response.json()
            except ValueError:
                base_result["error_code"] = "invalid_response"
                base_result["message"] = "返回不是合法 JSON"
                return base_result
            if not isinstance(data, dict):
                base_result["error_code"] = "invalid_response"
                base_result["message"] = "返回结构不是 JSON 对象"
                return base_result
            code = data.get("code")
            if code not in (None, 0):
                base_result["error_code"] = "upstream_error"
                base_result["message"] = (
                    f"星辰业务错误 {code}：{str(data.get('message') or '').strip()}"
                )
                return base_result
            choices = data.get("choices")
            if not isinstance(choices, list) or not choices:
                base_result["error_code"] = "invalid_response"
                base_result["message"] = "返回缺少 choices"
                return base_result
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, str) or not content.strip():
                base_result["error_code"] = "invalid_response"
                base_result["message"] = "返回没有可用回答文本"
                return base_result
            base_result["success"] = True
            base_result["message"] = f"连接成功（回答 {len(content.strip())} 字）"
            return base_result
        if is_metaso_web_search_entry(entry):
            # 秘塔业务错误同样返回 HTTP 200（如密钥无效是 errCode=401），
            # 不能只看状态码，否则错误 Key 会被误判为连接成功。
            try:
                data = response.json()
            except ValueError:
                base_result["error_code"] = "invalid_response"
                base_result["message"] = "返回不是合法 JSON"
                return base_result
            if not isinstance(data, dict):
                base_result["error_code"] = "invalid_response"
                base_result["message"] = "返回结构不是 JSON 对象"
                return base_result
            code = data.get("errCode")
            if code not in (None, 0):
                if code in (401, 403):
                    base_result["error_code"] = "auth_failed"
                elif code == 429:
                    base_result["error_code"] = "rate_limited"
                else:
                    base_result["error_code"] = "upstream_error"
                base_result["message"] = (
                    f"秘塔业务错误 {code}：{str(data.get('errMsg') or '').strip()}"
                )
                return base_result
            choices = data.get("choices")
            if not isinstance(choices, list) or not choices:
                base_result["error_code"] = "invalid_response"
                base_result["message"] = "返回缺少 choices"
                return base_result
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, str) or not content.strip():
                base_result["error_code"] = "invalid_response"
                base_result["message"] = "返回没有可用回答文本"
                return base_result
            citations = message.get("citations") if isinstance(message, dict) else None
            citation_count = len(citations) if isinstance(citations, list) else 0
            base_result["success"] = True
            base_result["message"] = (
                f"连接成功（回答 {len(content.strip())} 字，引用 {citation_count} 条）"
            )
            return base_result
        base_result["success"] = True
        base_result["message"] = "连接成功"
        return base_result
    if status in (401, 403):
        if is_spark_maas_entry(entry):
            code, detail = _spark_error_detail(response)
            if code == 11200:
                base_result["error_code"] = "permission_denied"
                base_result["message"] = (
                    f"星辰授权失败 {code}：{detail or '账户无有效订单或额度'}"
                    "；请在星辰控制台为模型开通订单/额度"
                )
                return base_result
            if detail:
                base_result["error_code"] = (
                    "auth_failed" if status == 401 else "upstream_error"
                )
                base_result["message"] = f"星辰业务错误 {code or status}：{detail}"
                return base_result
        base_result["error_code"] = "auth_failed"
        base_result["message"] = f"鉴权失败（HTTP {status}）"
    elif status == 404:
        base_result["error_code"] = "endpoint_not_found"
        expected = "/v2" if is_spark_maas_entry(entry) else "/v1"
        base_result["message"] = f"接口路径不存在，检查 entry_url 是否包含正确的 {expected}"
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
