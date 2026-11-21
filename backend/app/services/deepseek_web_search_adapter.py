"""DeepSeek 服务端联网搜索（Responses API + `deepseek_web_search`）适配器。

DeepSeek 唯一主路径（原 `deepseek_search` 的 `/v1/tools/search` 已于 2026-11-17 永久删除）：
本适配器调 `/responses` 并声明 `tools:[{"type":"deepseek_web_search"}]`，由模型先搜索/打开网页
再作答，返回**生成回答 + `url_citation` 引用**（`answer_kind=answer`），与 DeepSeek 网页端一致。

官方形态（2026-11 文档）：
`POST https://api.deepseek.com/responses`
body: model(`deepseek-flash`) + tools:[{"type": "deepseek_web_search"}] + input + stream=false
resp: output[]（reasoning / web_search_call / message），
      `message.content[].annotations[]` 为 `{"type":"url_citation","url","title"}`；
      `web_search_call.action` 含 `type`（search/open_page/find_in_page）与 `queries`/`url`。
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.credentials import read_credential_env
from app.models import MonitoringTask, QuestionVersion
from app.models.enums import FailureCode
from app.services.monitoring_collection import (
    AccessBlockedFailure,
    CollectionFailure,
    RateLimitedFailure,
    TransientCollectionFailure,
)
from app.services.monitoring_extraction import AnswerPayload, CitationInput, citation_from_item

DEFAULT_ENDPOINT = "https://api.deepseek.com/responses"
DEFAULT_MODEL = "deepseek-flash"
DEFAULT_CREDENTIAL_REF = "DEEPSEEK_API_KEY"
MAX_QUERY_CHARS = 4000


def _answer_text(data: dict[str, Any]) -> str:
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
    result: list[CitationInput] = []
    seen: set[str] = set()
    for item in data.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
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
    """把 web_search_call 的 action 抽出来，供排查“搜了什么、开了哪些页”。"""
    actions: list[dict[str, Any]] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "web_search_call":
            continue
        action = item.get("action")
        if isinstance(action, dict):
            actions.append(
                {
                    "kind": item.get("kind"),
                    "action": action.get("type"),
                    "queries": action.get("queries") or [],
                    "url": action.get("url"),
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
    if not isinstance(error, dict):
        return "", ""
    return str(error.get("code") or "").strip(), str(error.get("message") or "").strip()


class DeepSeekWebSearchAdapter:
    """把 Responses 服务的生成回答与 url_citation 归一成 AnswerPayload。"""

    def __init__(
        self,
        db: Session,
        *,
        api_key: str,
        model: str,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout_seconds: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._db = db
        self.api_key = api_key.strip()
        self.model = model.strip() or DEFAULT_MODEL
        self.endpoint = endpoint.rstrip("/") or DEFAULT_ENDPOINT
        self.last_request_payload: dict[str, Any] | None = None
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "DeepSeekWebSearchAdapter":
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
            "tools": [{"type": "deepseek_web_search"}],
            "input": self._question_text(task),
            "stream": False,
        }

    def collect(self, task: MonitoringTask) -> AnswerPayload:
        return self._collect(task, request_payload=None)

    def collect_with_request(
        self,
        task: MonitoringTask,
        request_payload: dict[str, Any],
    ) -> AnswerPayload:
        """按留存请求体回放；Authorization 仍从当前环境变量取。"""
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
                f"DeepSeek 联网搜索请求超时: {exc}",
                failure_code=FailureCode.TIMEOUT,
            ) from exc
        except httpx.HTTPError as exc:
            raise AccessBlockedFailure(f"DeepSeek 联网搜索服务不可达: {exc}") from exc

        status = response.status_code
        if status == 429:
            raise RateLimitedFailure("DeepSeek 联网搜索触发限流（HTTP 429）")
        if status in (401, 402, 403):
            code, message = _error_detail(response)
            detail = f"（{code}：{message}）" if code or message else ""
            raise AccessBlockedFailure(f"DeepSeek 联网搜索鉴权失败（HTTP {status}）{detail}")
        if status in (408, 504):
            raise TransientCollectionFailure(
                f"DeepSeek 联网搜索超时（HTTP {status}）",
                failure_code=FailureCode.TIMEOUT,
            )
        if status >= 500:
            raise TransientCollectionFailure(
                f"DeepSeek 联网搜索服务异常（HTTP {status}）",
                failure_code=FailureCode.OTHER,
            )
        if status >= 400:
            code, message = _error_detail(response)
            detail = " ".join(part for part in (code, message) if part)
            raise CollectionFailure(
                f"DeepSeek 联网搜索请求被拒绝（HTTP {status}）{(' ' + detail) if detail else ''}",
                failure_code=FailureCode.OTHER,
                retryable=False,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise TransientCollectionFailure(
                "DeepSeek 联网搜索返回不是合法 JSON",
                failure_code=FailureCode.OTHER,
            ) from exc
        if not isinstance(data, dict):
            raise TransientCollectionFailure(
                "DeepSeek 联网搜索返回结构不是 JSON 对象",
                failure_code=FailureCode.OTHER,
            )

        error = data.get("error")
        if isinstance(error, dict):
            code = str(error.get("code") or "").strip()
            message = str(error.get("message") or "").strip()
            raise CollectionFailure(
                f"DeepSeek 联网搜索失败：{code} {message}".strip(),
                failure_code=FailureCode.OTHER,
                retryable=False,
            )

        text = _answer_text(data)
        if not text:
            raise TransientCollectionFailure(
                "DeepSeek 联网搜索返回没有可用回答文本",
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
            engine_model=str(data.get("model") or self.model),
            model_version=self.model,
            country_code="CN",
            language="zh",
            citations=citations,
            prompt_tokens=usage.get("input_tokens"),
            completion_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
        )


def build_deepseek_web_search_adapter(
    db: Session,
    *,
    credential_ref: str | None,
    model_name: str | None,
    entry_url: str | None = None,
    stored_secret: str | None = None,
    timeout_seconds: float = 120.0,
    client: httpx.Client | None = None,
) -> DeepSeekWebSearchAdapter:
    """系统内填写的密钥优先；否则从 credential_ref（默认 DEEPSEEK_API_KEY）读；模型默认 deepseek-flash。"""
    ref = (credential_ref or "").strip() or DEFAULT_CREDENTIAL_REF
    api_key = (stored_secret or "").strip() or read_credential_env(ref)
    if not api_key:
        raise AccessBlockedFailure(
            f"未配置密钥（系统内填写或环境变量 {ref}），DeepSeek 联网搜索入口无法调用"
        )
    return DeepSeekWebSearchAdapter(
        db,
        api_key=api_key,
        model=(model_name or "").strip() or DEFAULT_MODEL,
        endpoint=entry_url or DEFAULT_ENDPOINT,
        timeout_seconds=timeout_seconds,
        client=client,
    )
