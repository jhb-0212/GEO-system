"""DeepSeek 官方搜索 API（`POST /v1/tools/search`）适配器。

边界（和元宝搜索一致）：
- 该接口返回的是**检索结果**（title/url/snippet/summary），不是对话生成答案；
  本适配器把结果归一成可审计的检索摘要文本，并逐条写 citations，不冒充模型回答。
  报表里通过 `engine_model=deepseek-search` 与 `raw_response.answer_kind=search_result` 区分口径。
- 只读：Search / Fetch 都是只读接口，不落额外状态。
- 凭证：API Key 只从环境变量读；库里只存 credential_ref（变量名），不落明文。
- 频控：账号级 QPS 100（Search）/ 25（Fetch），429 直接按限流处理，不做连续重试。

官方参数：query 1–128 字符、count 1–50、need_content 控制是否返回正文（默认关，
省 token；需要正文时由运营在入口上显式开启）。
"""

from __future__ import annotations

import json
import os
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

DEFAULT_ENDPOINT = "https://api.deepseek.com/v1/tools/search"
DEFAULT_MODEL = "deepseek-search"
DEFAULT_CREDENTIAL_REF = "DEEPSEEK_API_KEY"
MAX_RESULTS = 10
MAX_QUERY_CHARS = 128


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _results(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = data.get("results")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _answer_text(results: list[dict[str, Any]]) -> str:
    """把检索结果拼成可审计文本：编号 + 标题 + 摘要 + URL。"""
    lines: list[str] = []
    for index, item in enumerate(results[:MAX_RESULTS], start=1):
        title = _clean_text(item.get("title"))
        summary = _clean_text(item.get("summary") or item.get("snippet"))
        url = str(item.get("url") or "").strip()
        block = [f"[{index}] {title}" if title else f"[{index}]"]
        if summary:
            block.append(summary)
        if url:
            block.append(url)
        lines.append("\n".join(block))
    return "\n\n".join(lines).strip()


def _citations(results: list[dict[str, Any]]) -> list[CitationInput]:
    deduped: list[CitationInput] = []
    seen: set[str] = set()
    for item in results[:MAX_RESULTS]:
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(CitationInput(url=url))
    return deduped


class DeepSeekSearchAdapter:
    """把 `/v1/tools/search` 的检索结果归一成监测样本可用的 AnswerPayload。"""

    def __init__(
        self,
        db: Session,
        *,
        api_key: str,
        endpoint: str = DEFAULT_ENDPOINT,
        count: int = MAX_RESULTS,
        need_content: bool = False,
        timeout_seconds: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._db = db
        self.api_key = api_key.strip()
        self.endpoint = endpoint.rstrip("/") or DEFAULT_ENDPOINT
        self.count = max(1, min(50, int(count)))
        self.need_content = bool(need_content)
        self.last_request_payload: dict[str, Any] | None = None
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "DeepSeekSearchAdapter":
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

    def collect(self, task: MonitoringTask) -> AnswerPayload:
        query = self._question_text(task)
        if len(query) > MAX_QUERY_CHARS:
            raise CollectionFailure(
                f"问题超过搜索接口 {MAX_QUERY_CHARS} 字符上限",
                failure_code=FailureCode.OTHER,
                retryable=False,
            )
        body = {"query": query, "count": self.count}
        if self.need_content:
            body["need_content"] = True
        self.last_request_payload = {"method": "POST", "url": self.endpoint, "body": body}
        try:
            response = self._client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        except httpx.TimeoutException as exc:
            raise TransientCollectionFailure(
                f"DeepSeek 搜索请求超时: {exc}",
                failure_code=FailureCode.TIMEOUT,
            ) from exc
        except httpx.HTTPError as exc:
            raise AccessBlockedFailure(f"DeepSeek 搜索服务不可达: {exc}") from exc

        status = response.status_code
        if status == 429:
            raise RateLimitedFailure("DeepSeek 搜索触发限流（HTTP 429）")
        if status in (401, 403):
            raise AccessBlockedFailure(f"DeepSeek 搜索鉴权失败（HTTP {status}）")
        if status == 402:
            raise AccessBlockedFailure("DeepSeek 账户余额不足（HTTP 402）")
        if status in (408, 504) or status >= 500:
            raise TransientCollectionFailure(
                f"DeepSeek 搜索服务异常（HTTP {status}）",
                failure_code=FailureCode.OTHER,
            )
        if status >= 400:
            raise CollectionFailure(
                f"DeepSeek 搜索请求被拒绝（HTTP {status}）",
                failure_code=FailureCode.OTHER,
                retryable=False,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise TransientCollectionFailure(
                "DeepSeek 搜索返回不是合法 JSON",
                failure_code=FailureCode.OTHER,
            ) from exc
        if not isinstance(data, dict):
            raise TransientCollectionFailure(
                "DeepSeek 搜索返回结构不是 JSON 对象",
                failure_code=FailureCode.OTHER,
            )
        error = data.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "").strip()
            code = str(error.get("code") or "").strip()
            raise CollectionFailure(
                f"DeepSeek 搜索失败：{code} {message}".strip(),
                failure_code=FailureCode.OTHER,
                retryable=False,
            )

        all_results = _results(data)
        results = all_results[:MAX_RESULTS]
        return AnswerPayload(
            text=_answer_text(results),
            raw_response={
                "query": query,
                "count": self.count,
                "result_count": len(results),
                "total_results": len(all_results),
                "answer_kind": "search_result",
                "results": results,
            },
            engine_model=DEFAULT_MODEL,
            citations=_citations(results),
        )


def build_deepseek_search_adapter(
    db: Session,
    *,
    credential_ref: str | None,
    entry_url: str | None = None,
    count: int = MAX_RESULTS,
    timeout_seconds: float = 60.0,
    client: httpx.Client | None = None,
) -> DeepSeekSearchAdapter:
    """从 credential_ref（默认 DEEPSEEK_API_KEY）读 API Key，不回显明文。"""
    ref = (credential_ref or "").strip() or DEFAULT_CREDENTIAL_REF
    api_key = read_credential_env(ref)
    if not api_key:
        raise AccessBlockedFailure(f"环境变量 {ref} 未配置，DeepSeek 搜索入口无法调用")
    return DeepSeekSearchAdapter(
        db,
        api_key=api_key,
        endpoint=entry_url or DEFAULT_ENDPOINT,
        count=count,
        timeout_seconds=timeout_seconds,
        client=client,
    )
