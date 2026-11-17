"""豆包搜索（火山方舟 Responses API + `web_search` 工具）适配器。

边界：
- 这是**生成式回答 + 联网引用**：模型会先搜索再作答，`output` 里既有
  `web_search_call`（实际 search query）也有 `message`（最终回答与 url_citation 标注）。
  因此 `answer_kind` 记为 `answer`，提及率按“回答内容”统计，与元宝/DeepSeek
  检索结果的 `search_result` 口径区分。
- 引用逐条来自 `output[].content[].annotations[]`（`type=url_citation`），按 URL 去重；
  没有 annotations 时 citations 为空，`citation_share` 如实为 0，不拿正文里的链接兜底。
- 凭据只从环境变量读；库里只存 credential_ref（默认 `ARK_API_KEY`），不落明文。

官方形态（2026-11 文档）：
`POST https://ark.cn-beijing.volces.com/api/v3/responses`
body: model + tools:[{"type":"web_search","sources":["doubao"]}] + input
resp: output[]（reasoning / web_search_call / message），usage.tool_usage.web_search
"""

from __future__ import annotations

import json
from typing import Any

import httpx
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
from app.services.monitoring_extraction import AnswerPayload, CitationInput

DEFAULT_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3/responses"
DEFAULT_MODEL = "doubao-seed-2-1-pro-260915"
DEFAULT_CREDENTIAL_REF = "ARK_API_KEY"
DEFAULT_SOURCES = ("doubao",)


def _answer_text(data: dict[str, Any]) -> str:
    output = data.get("output")
    if not isinstance(output, list):
        return ""
    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "output_text":
                text = str(block.get("text") or "").strip()
                if text:
                    parts.append(text)
    return "\n\n".join(parts).strip()


def _citations(data: dict[str, Any]) -> list[CitationInput]:
    output = data.get("output")
    if not isinstance(output, list):
        return []
    deduped: list[CitationInput] = []
    seen: set[str] = set()
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            annotations = block.get("annotations")
            if not isinstance(annotations, list):
                continue
            for annotation in annotations:
                if not isinstance(annotation, dict):
                    continue
                if annotation.get("type") != "url_citation":
                    continue
                url = str(annotation.get("url") or "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                deduped.append(CitationInput(url=url))
    return deduped


def _search_calls(data: dict[str, Any]) -> list[str]:
    output = data.get("output")
    if not isinstance(output, list):
        return []
    queries: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "web_search_call":
            continue
        action = item.get("action")
        if not isinstance(action, dict):
            continue
        for key in ("query", "queries"):
            value = action.get(key)
            if isinstance(value, str) and value.strip() and value not in queries:
                queries.append(value.strip())
            elif isinstance(value, list):
                for entry in value:
                    if isinstance(entry, str) and entry.strip() and entry not in queries:
                        queries.append(entry.strip())
    return queries


class DoubaoSearchAdapter:
    """把方舟 Responses 的生成回答与 url_citation 归一成 AnswerPayload。"""

    def __init__(
        self,
        db: Session,
        *,
        api_key: str,
        model: str,
        endpoint: str = DEFAULT_ENDPOINT,
        sources: tuple[str, ...] = DEFAULT_SOURCES,
        timeout_seconds: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._db = db
        self.api_key = api_key.strip()
        self.model = model
        self.endpoint = endpoint.rstrip("/") or DEFAULT_ENDPOINT
        self.sources = tuple(sources) or DEFAULT_SOURCES
        self.last_request_payload: dict[str, Any] | None = None
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "DoubaoSearchAdapter":
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
        return version.text.strip()

    def _build_body(self, task: MonitoringTask) -> dict[str, Any]:
        return {
            "model": self.model,
            "tools": [{"type": "web_search", "sources": list(self.sources)}],
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": self._question_text(task)}],
                }
            ],
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
                f"豆包搜索请求超时: {exc}",
                failure_code=FailureCode.TIMEOUT,
            ) from exc
        except httpx.HTTPError as exc:
            raise AccessBlockedFailure(f"豆包搜索服务不可达: {exc}") from exc

        status = response.status_code
        if status == 429:
            raise RateLimitedFailure("豆包搜索触发限流（HTTP 429）")
        if status in (401, 403):
            raise AccessBlockedFailure(f"豆包搜索鉴权失败（HTTP {status}）")
        if status >= 500:
            raise TransientCollectionFailure(
                f"豆包搜索服务异常（HTTP {status}）",
                failure_code=FailureCode.OTHER,
            )
        if status >= 400:
            raise CollectionFailure(
                f"豆包搜索请求被拒绝（HTTP {status}）",
                failure_code=FailureCode.OTHER,
                retryable=False,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise TransientCollectionFailure(
                "豆包搜索返回不是合法 JSON",
                failure_code=FailureCode.OTHER,
            ) from exc
        if not isinstance(data, dict):
            raise TransientCollectionFailure(
                "豆包搜索返回结构不是 JSON 对象",
                failure_code=FailureCode.OTHER,
            )

        error = data.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "").strip()
            code = str(error.get("code") or "").strip()
            raise CollectionFailure(
                f"豆包搜索失败：{code} {message}".strip(),
                failure_code=FailureCode.OTHER,
                retryable=False,
            )

        text = _answer_text(data)
        if not text:
            raise TransientCollectionFailure(
                "豆包搜索返回没有可用回答文本",
                failure_code=FailureCode.OTHER,
            )

        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return AnswerPayload(
            text=text,
            raw_response={
                "response_id": data.get("id"),
                "model": data.get("model"),
                "status": data.get("status"),
                "answer_kind": "answer",
                "search_queries": _search_calls(data),
                "citation_count": len(_citations(data)),
                "usage": usage,
                "output": data.get("output"),
            },
            engine_model=str(data.get("model") or self.model),
            model_version=self.model,
            country_code="CN",
            language="zh",
            citations=_citations(data),
            prompt_tokens=usage.get("input_tokens"),
            completion_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
        )


def build_doubao_search_adapter(
    db: Session,
    *,
    credential_ref: str | None,
    model_name: str | None,
    entry_url: str | None = None,
    timeout_seconds: float = 120.0,
    client: httpx.Client | None = None,
) -> DoubaoSearchAdapter:
    """从 credential_ref（默认 ARK_API_KEY）读 key；模型名取入口配置。"""
    ref = (credential_ref or "").strip() or DEFAULT_CREDENTIAL_REF
    api_key = read_credential_env(ref)
    if not api_key:
        raise AccessBlockedFailure(f"环境变量 {ref} 未配置，豆包搜索入口无法调用")
    model = (model_name or "").strip()
    if not model:
        raise AccessBlockedFailure("豆包搜索入口未配置 model_name")
    return DoubaoSearchAdapter(
        db,
        api_key=api_key,
        model=model,
        endpoint=entry_url or DEFAULT_ENDPOINT,
        timeout_seconds=timeout_seconds,
        client=client,
    )
