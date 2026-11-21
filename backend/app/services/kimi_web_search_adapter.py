"""Kimi 服务端联网搜索（Responses API + `web_search`）适配器。

Kimi 的 Chat Completions `$web_search` 内置工具已进入下线周期；当前主路径是
`POST /v1/responses`，在 tools 中声明 `{"type": "web_search"}`，由服务端搜索后
注入上下文并生成回答。`include` 打开 `web_search_call.action.sources` 后，
响应会返回命中的网页标题与 URL，作为引用来源落库。

官方形态（2026-11 文档）：
body: model(`kimi-k3`) + input + tools:[{"type":"web_search"}] +
      include:["web_search_call.action.sources"] + stream=false
resp: output[]（web_search_call / reasoning / message）；
      `web_search_call.action.sources[]` 为 `{"type":"url","url","title"}`。
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.credentials import read_credential_env
from app.models import MonitoringTask, QuestionVersion
from app.models.enums import AnswerKind, FailureCode
from app.services.local_llm_adapter import DEFAULT_SYSTEM_PROMPT
from app.services.monitoring_collection import (
    AccessBlockedFailure,
    CollectionFailure,
    RateLimitedFailure,
    TransientCollectionFailure,
)
from app.services.monitoring_extraction import AnswerPayload, CitationInput, citation_from_item

DEFAULT_ENDPOINT = "https://api.moonshot.cn/v1/responses"
DEFAULT_MODEL = "kimi-k3"
DEFAULT_CREDENTIAL_REF = "MOONSHOT_API_KEY"
MAX_QUERY_CHARS = 4000
# K3 是强制思考模型；输出预算太小时推理会吃掉全部 token，没有最终回答。
# 官方建议思考模型至少 16000，并用 reasoning_effort=low 控制首轮延迟/成本。
MAX_OUTPUT_TOKENS = 16000
REASONING_EFFORT = "low"


def _answer_text(data: dict[str, Any]) -> str:
    """Responses 的 message.content[].output_text 拼成回答正文。"""
    parts: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for block in item.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "output_text":
                text = str(block.get("text") or "").strip()
                if text:
                    parts.append(text)
    return "\n\n".join(parts).strip()


def _citations(data: dict[str, Any]) -> list[CitationInput]:
    """优先取 web_search_call.action.sources，再兼容 url_citation 注解。"""
    result: list[CitationInput] = []
    seen: set[str] = set()

    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "web_search_call":
            action = item.get("action")
            if not isinstance(action, dict):
                continue
            for source in action.get("sources") or []:
                if not isinstance(source, dict):
                    continue
                citation = citation_from_item(source)
                if citation is None or citation.url in seen:
                    continue
                seen.add(citation.url)
                result.append(citation)
            continue

        if item.get("type") != "message":
            continue
        for block in item.get("content") or []:
            if not isinstance(block, dict):
                continue
            for annotation in block.get("annotations") or []:
                if not isinstance(annotation, dict):
                    continue
                if annotation.get("type") != "url_citation":
                    continue
                citation = citation_from_item(annotation)
                if citation is None or citation.url in seen:
                    continue
                seen.add(citation.url)
                result.append(citation)
    return result


def _search_actions(data: dict[str, Any]) -> list[dict[str, Any]]:
    """留下“搜了什么、命中几条来源”，便于排障与审计。"""
    actions: list[dict[str, Any]] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "web_search_call":
            continue
        action = item.get("action")
        if not isinstance(action, dict):
            continue
        sources = [s for s in action.get("sources") or [] if isinstance(s, dict)]
        actions.append(
            {
                "status": item.get("status"),
                "action": action.get("type"),
                "query": action.get("queries") or action.get("query"),
                "source_count": len(sources),
            }
        )
    return actions


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
    # DashScope 的错误有时是顶层 code/message，不再套一层 error。
    return str(data.get("code") or "").strip(), str(data.get("message") or "").strip()


class KimiWebSearchAdapter:
    """把 Kimi Responses 的生成回答与网页来源归一成 AnswerPayload。"""

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
        provider_label: str = "Kimi",
    ) -> None:
        self._db = db
        self.api_key = api_key.strip()
        self.model = model.strip() or DEFAULT_MODEL
        self.endpoint = endpoint.rstrip("/") or DEFAULT_ENDPOINT
        self.system_prompt = system_prompt
        self.provider_label = provider_label
        self.last_request_payload: dict[str, Any] | None = None
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "KimiWebSearchAdapter":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _question_text(self, task: MonitoringTask) -> str:
        version = self._db.get(QuestionVersion, task.question_version_id)
        if version is None or not version.text.strip():
            raise CollectionFailure(
                "任务关联的问题版本不存在或为空",
                failure_code=FailureCode.OTHER,
                retryable=False,
            )
        return version.text.strip()[:MAX_QUERY_CHARS]

    def _build_body(self, task: MonitoringTask) -> dict[str, Any]:
        return {
            "model": self.model,
            "instructions": self.system_prompt,
            "input": self._question_text(task),
            "tools": [{"type": "web_search"}],
            "include": ["web_search_call.action.sources"],
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "reasoning_effort": REASONING_EFFORT,
            "stream": False,
        }

    def collect(self, task: MonitoringTask) -> AnswerPayload:
        return self._collect(task, request_payload=None)

    def collect_with_request(
        self,
        task: MonitoringTask,
        request_payload: dict[str, Any],
    ) -> AnswerPayload:
        """按留存请求体回放；Authorization 仍从当前配置读取。"""
        return self._collect(task, request_payload=request_payload)

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
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            )
        except httpx.TimeoutException as exc:
            raise TransientCollectionFailure(
                f"{self.provider_label}联网搜索请求超时: {exc}",
                failure_code=FailureCode.TIMEOUT,
            ) from exc
        except httpx.HTTPError as exc:
            raise AccessBlockedFailure(
                f"{self.provider_label}联网搜索服务不可达: {exc}"
            ) from exc

        status = response.status_code
        if status == 429:
            raise RateLimitedFailure(f"{self.provider_label}联网搜索触发限流（HTTP 429）")
        if status in (401, 403):
            code, message = _error_detail(response)
            detail = f"（{code}：{message}）" if code or message else ""
            raise AccessBlockedFailure(f"{self.provider_label}联网搜索鉴权失败（HTTP {status}）{detail}")
        if status in (408, 504):
            raise TransientCollectionFailure(
                f"{self.provider_label}联网搜索超时（HTTP {status}）",
                failure_code=FailureCode.TIMEOUT,
            )
        if status >= 500:
            raise TransientCollectionFailure(
                f"{self.provider_label}联网搜索服务异常（HTTP {status}）",
                failure_code=FailureCode.OTHER,
            )
        if status >= 400:
            code, message = _error_detail(response)
            detail = " ".join(part for part in (code, message) if part)
            raise CollectionFailure(
                f"{self.provider_label}联网搜索请求被拒绝（HTTP {status}）{(' ' + detail) if detail else ''}",
                failure_code=FailureCode.OTHER,
                retryable=False,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise TransientCollectionFailure(
                f"{self.provider_label}联网搜索返回不是合法 JSON",
                failure_code=FailureCode.OTHER,
            ) from exc
        if not isinstance(data, dict):
            raise TransientCollectionFailure(
                f"{self.provider_label}联网搜索返回结构不是 JSON 对象",
                failure_code=FailureCode.OTHER,
            )

        error = data.get("error")
        if isinstance(error, dict):
            code = str(error.get("code") or "").strip()
            message = str(error.get("message") or "").strip()
            raise CollectionFailure(
                f"{self.provider_label}联网搜索失败：{code} {message}".strip(),
                failure_code=FailureCode.OTHER,
                retryable=False,
            )
        # DashScope 等平台可能把错误放在顶层 code/message。
        code = str(data.get("code") or "").strip()
        message = str(data.get("message") or "").strip()
        if code or message:
            raise CollectionFailure(
                f"{self.provider_label}联网搜索失败：{code} {message}".strip(),
                failure_code=FailureCode.OTHER,
                retryable=False,
            )

        text = _answer_text(data)
        if not text:
            raise TransientCollectionFailure(
                f"{self.provider_label}联网搜索返回没有可用回答文本",
                failure_code=FailureCode.OTHER,
            )

        citations = _citations(data)
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        output = data.get("output") if isinstance(data.get("output"), list) else []
        return AnswerPayload(
            text=text,
            raw_response={
                "response_id": data.get("id"),
                "model": data.get("model"),
                "status": data.get("status"),
                "answer_kind": "answer",
                "search_actions": _search_actions(data),
                "citation_count": len(citations),
                "usage": usage,
                "output": output,
            },
            answer_kind=AnswerKind.ANSWER,
            engine_model=str(data.get("model") or self.model),
            model_version=self.model,
            country_code="CN",
            language="zh",
            citations=citations,
            prompt_tokens=usage.get("input_tokens"),
            completion_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
        )


def build_kimi_web_search_adapter(
    db: Session,
    *,
    credential_ref: str | None,
    model_name: str | None,
    entry_url: str | None = None,
    stored_secret: str | None = None,
    timeout_seconds: float = 120.0,
    client: httpx.Client | None = None,
    provider_label: str = "Kimi",
) -> KimiWebSearchAdapter:
    """系统内填写的密钥优先；否则从 credential_ref（默认 MOONSHOT_API_KEY）读。"""
    ref = (credential_ref or "").strip() or DEFAULT_CREDENTIAL_REF
    api_key = (stored_secret or "").strip() or read_credential_env(ref)
    if not api_key:
        raise AccessBlockedFailure(
            f"未配置密钥（系统内填写或环境变量 {ref}），{provider_label}联网搜索入口无法调用"
        )
    endpoint = (entry_url or "").strip() or DEFAULT_ENDPOINT
    if not endpoint.rstrip("/").endswith("/responses"):
        endpoint = f"{endpoint.rstrip('/')}/responses"
    return KimiWebSearchAdapter(
        db,
        api_key=api_key,
        model=(model_name or "").strip() or DEFAULT_MODEL,
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
        client=client,
        provider_label=provider_label,
    )
