"""360 智脑 AI 搜索（`/v1/search/aisearch`）适配器。

官方文档：`360 智脑大模型 API` 的 AI 搜索入口基于 `aiso-max`，直接生成
回答，并在响应顶层返回 `references`；`enable_corner_markers=true` 时正文
还会带 `[[n](url)]` 角标。适配器把 `references` 归一成系统引用，正文角标
只作为兜底，避免平台未返回结构化 references 时引用为 0。

入口仍登记为 `openai_compatible`，因为鉴权和消息形态是 OpenAI 风格；
但 endpoint 不是 `/chat/completions`，而是固定的 `/v1/search/aisearch`。
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.credentials import read_credential_env
from app.models import MonitoringTask
from app.models.enums import AnswerKind, FailureCode
from app.services.local_llm_adapter import DEFAULT_SYSTEM_PROMPT, LocalLLMAdapter, _extract_text
from app.services.monitoring_collection import (
    AccessBlockedFailure,
    CollectionFailure,
    RateLimitedFailure,
    TransientCollectionFailure,
)
from app.services.monitoring_extraction import AnswerPayload, CitationInput, citation_from_item

DEFAULT_ENDPOINT = "https://api.360.cn/v1/search/aisearch"
DEFAULT_MODEL = "360gpt-pro"
DEFAULT_CREDENTIAL_REF = "QIHU360_API_KEY"
MAX_QUERY_CHARS = 4000
MAX_REFER_SEARCH_ITEMS = 20
PROVIDER_LABEL = "360 智脑"

_CORNER_CITATION_RE = re.compile(r"\[\[[^\]]*\]\((https?://[^)\s]+)\)\]")
_MARKDOWN_CITATION_RE = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)")


def build_request_body(question: str, model: str = DEFAULT_MODEL) -> dict[str, Any]:
    """AI 搜索请求体；不发送 Chat 的 temperature/max_tokens 等参数。"""
    return {
        "model": model,
        "messages": [{"role": "user", "content": question[:MAX_QUERY_CHARS]}],
        "stream": False,
        "max_refer_search_items": MAX_REFER_SEARCH_ITEMS,
        "enable_corner_markers": True,
        "enable_web_page_safety": True,
        "search_mode": "required",
    }


def _containers(data: dict[str, Any]) -> list[dict[str, Any]]:
    """收集可能承载 references 的对象，兼容顶层与常见嵌套包装。"""
    result: list[dict[str, Any]] = [data]
    for key in ("data", "result"):
        nested = data.get(key)
        if isinstance(nested, dict):
            result.append(nested)
    choices = data.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        first = choices[0]
        result.append(first)
        message = first.get("message")
        if isinstance(message, dict):
            result.append(message)
    return result


def _normalize_reference(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    normalized.update(
        {
            "url": item.get("url") or item.get("purl") or item.get("link"),
            "title": item.get("title"),
            "site_name": item.get("site_name") or item.get("site"),
            "snippet": item.get("summary_ai")
            or item.get("summary")
            or item.get("contentdtl")
            or item.get("content"),
            "published_at": item.get("page_time")
            or item.get("published_at")
            or item.get("date"),
            "position": item.get("rank") or item.get("position"),
        }
    )
    return normalized


def _citations(data: dict[str, Any]) -> list[CitationInput]:
    """优先 references，其次正文角标；按 URL 去重。"""
    citations: list[CitationInput] = []
    seen: set[str] = set()

    for container in _containers(data):
        raw_references = container.get("references")
        if not isinstance(raw_references, list):
            continue
        for item in raw_references:
            if not isinstance(item, dict):
                continue
            normalized = _normalize_reference(item)
            citation = citation_from_item(normalized)
            if citation is None or citation.url in seen:
                continue
            seen.add(citation.url)
            citations.append(citation)

    text = _extract_text(data)
    patterns = (_CORNER_CITATION_RE, _MARKDOWN_CITATION_RE)
    for pattern in patterns:
        for match in pattern.finditer(text):
            url = match.group(1).strip()
            if not url or url in seen:
                continue
            seen.add(url)
            citations.append(CitationInput(url=url))

    return citations


def _error_detail(response: httpx.Response) -> tuple[str, str]:
    try:
        data = response.json()
    except ValueError:
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    error = data.get("error")
    if isinstance(error, dict):
        return str(error.get("code") or "").strip(), str(error.get("message") or "").strip()
    return str(data.get("code") or "").strip(), str(data.get("message") or "").strip()


def _response_code(data: dict[str, Any]) -> str:
    for key in ("code", "errno"):
        value = data.get(key)
        if value is None or value in (0, "0", ""):
            continue
        return str(value)
    return ""


class Qihu360SearchAdapter(LocalLLMAdapter):
    """360 智脑 AI 搜索：生成回答 + references 引用。"""

    def __init__(
        self,
        db: Session,
        *,
        api_key: str,
        model: str,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout_seconds: float = 120.0,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(
            db,
            base_url=endpoint,
            model=model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            system_prompt=system_prompt,
            client=client,
        )
        self.endpoint = endpoint.rstrip("/")

    def _chat_url(self) -> str:
        return self.endpoint

    def _build_body(self, task: MonitoringTask) -> dict[str, Any]:
        return build_request_body(self._question_text(task), self.model)

    def _collect(
        self,
        task: MonitoringTask,
        *,
        request_payload: dict[str, Any] | None,
    ) -> AnswerPayload:
        body = dict(request_payload) if request_payload is not None else self._build_body(task)
        self.last_request_payload = body
        try:
            response = self._client.post(
                self._chat_url(),
                headers=self._headers(),
                content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            )
        except httpx.TimeoutException as exc:
            raise TransientCollectionFailure(
                f"{PROVIDER_LABEL} AI 搜索请求超时: {exc}",
                failure_code=FailureCode.TIMEOUT,
            ) from exc
        except httpx.HTTPError as exc:
            raise AccessBlockedFailure(f"{PROVIDER_LABEL} AI 搜索服务不可达: {exc}") from exc

        status = response.status_code
        if status == 429:
            raise RateLimitedFailure(f"{PROVIDER_LABEL} AI 搜索触发限流（HTTP 429）")
        if status in (401, 403):
            code, message = _error_detail(response)
            detail = f"（{code}：{message}）" if code or message else ""
            raise AccessBlockedFailure(
                f"{PROVIDER_LABEL} AI 搜索鉴权失败（HTTP {status}）{detail}"
            )
        if status in (408, 504):
            raise TransientCollectionFailure(
                f"{PROVIDER_LABEL} AI 搜索超时（HTTP {status}）",
                failure_code=FailureCode.TIMEOUT,
            )
        if status >= 500:
            raise TransientCollectionFailure(
                f"{PROVIDER_LABEL} AI 搜索服务异常（HTTP {status}）",
                failure_code=FailureCode.OTHER,
            )
        if status >= 400:
            code, message = _error_detail(response)
            detail = " ".join(part for part in (code, message) if part)
            raise CollectionFailure(
                f"{PROVIDER_LABEL} AI 搜索请求被拒绝（HTTP {status}）"
                f"{(' ' + detail) if detail else ''}",
                failure_code=FailureCode.OTHER,
                retryable=False,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise TransientCollectionFailure(
                f"{PROVIDER_LABEL} AI 搜索返回不是合法 JSON",
                failure_code=FailureCode.OTHER,
            ) from exc
        if not isinstance(data, dict):
            raise TransientCollectionFailure(
                f"{PROVIDER_LABEL} AI 搜索返回结构不是 JSON 对象",
                failure_code=FailureCode.OTHER,
            )

        response_code = _response_code(data)
        if response_code:
            message = str(data.get("message") or "").strip()
            raise CollectionFailure(
                f"{PROVIDER_LABEL} AI 搜索失败：{response_code} {message}".strip(),
                failure_code=FailureCode.OTHER,
                retryable=False,
            )

        text = _extract_text(data)
        if not text:
            raise TransientCollectionFailure(
                f"{PROVIDER_LABEL} AI 搜索返回没有可用回答文本",
                failure_code=FailureCode.OTHER,
            )

        citations = _citations(data)
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        raw_response = dict(data)
        raw_response["citation_count"] = len(citations)
        return AnswerPayload(
            text=text,
            raw_response=raw_response,
            answer_kind=AnswerKind.ANSWER,
            engine_model=str(data.get("model") or self.model),
            model_version=self.model,
            country_code="CN",
            language="zh",
            citations=citations,
            prompt_tokens=usage.get("prompt_tokens") or usage.get("input_tokens"),
            completion_tokens=usage.get("completion_tokens") or usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
        )


def normalize_endpoint(value: str | None) -> str:
    endpoint = (value or "").strip() or DEFAULT_ENDPOINT
    endpoint = endpoint.rstrip("/")
    if endpoint.endswith("/aisearch"):
        return endpoint
    if endpoint.endswith("/v1/search"):
        return f"{endpoint}/aisearch"
    if endpoint.endswith("/v1"):
        return f"{endpoint}/search/aisearch"
    return f"{endpoint}/v1/search/aisearch"


def build_qihu360_search_adapter(
    db: Session,
    *,
    credential_ref: str | None,
    model_name: str | None,
    entry_url: str | None = None,
    stored_secret: str | None = None,
    timeout_seconds: float = 120.0,
    client: httpx.Client | None = None,
) -> Qihu360SearchAdapter:
    ref = (credential_ref or "").strip() or DEFAULT_CREDENTIAL_REF
    api_key = (stored_secret or "").strip() or read_credential_env(ref)
    if not api_key:
        raise AccessBlockedFailure(
            f"未配置密钥（系统内填写或环境变量 {ref}），{PROVIDER_LABEL} AI 搜索入口无法调用"
        )
    return Qihu360SearchAdapter(
        db,
        api_key=api_key,
        model=(model_name or "").strip() or DEFAULT_MODEL,
        endpoint=normalize_endpoint(entry_url),
        timeout_seconds=timeout_seconds,
        client=client,
    )


__all__ = [
    "DEFAULT_CREDENTIAL_REF",
    "DEFAULT_ENDPOINT",
    "DEFAULT_MODEL",
    "MAX_REFER_SEARCH_ITEMS",
    "Qihu360SearchAdapter",
    "build_qihu360_search_adapter",
    "build_request_body",
    "normalize_endpoint",
]
