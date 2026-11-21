"""文心 / 千帆 AI 搜索（`POST /v2/ai_search/web_search`）适配器。

边界：
- 这是**检索接口**：返回 `references` 列表（标题/URL/摘要/发布信息），不是文心对话生成答案；
  `answer_kind` 记为 `search_result`，报表口径写“文心搜索可见性”，不得与生成式回答的提及率混算。
- 官方示例（千帆 AI 搜索）请求体为 `{"messages":[{"role":"user","content":"..."}]}`，
  Authorization: Bearer <AppBuilder API Key>；返回 `references[]` + `request_id`。
- 兼容两种 references 元素：对象（title/url/snippet/date/website）与纯 URL 字符串；
  没有 references 时视为上游返回异常，不伪造“无引用”样本。
- 凭据只从环境变量读；库里只存 credential_ref（默认 `QIANFAN_API_KEY`），不落明文。
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
from app.services.monitoring_extraction import AnswerPayload, CitationInput, citation_from_item

DEFAULT_ENDPOINT = "https://qianfan.baidubce.com/v2/ai_search/web_search"
DEFAULT_MODEL = "wenxin-search"
DEFAULT_CREDENTIAL_REF = "QIANFAN_API_KEY"
MAX_RESULTS = 10


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normalize_reference(item: Any) -> dict[str, str] | None:
    if isinstance(item, str):
        url = item.strip()
        return {"url": url, "title": "", "snippet": "", "date": "", "website": ""} if url else None
    if not isinstance(item, dict):
        return None
    url = str(item.get("url") or item.get("link") or "").strip()
    if not url:
        return None
    return {
        "url": url,
        "title": _clean_text(item.get("title")),
        "snippet": _clean_text(item.get("snippet") or item.get("content")),
        "date": _clean_text(item.get("date") or item.get("publish_time")),
        "website": _clean_text(item.get("website") or item.get("site_name")),
    }


def _references(data: dict[str, Any]) -> list[dict[str, str]]:
    raw = data.get("references")
    if not isinstance(raw, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in raw:
        entry = _normalize_reference(item)
        if entry is not None:
            normalized.append(entry)
    return normalized


def _answer_text(references: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for index, item in enumerate(references[:MAX_RESULTS], start=1):
        parts = [f"[{index}] {item['title']}" if item["title"] else f"[{index}]"]
        if item["snippet"]:
            parts.append(item["snippet"])
        parts.append(item["url"])
        lines.append("\n".join(parts))
    return "\n\n".join(lines).strip()


def _citations(references: list[dict[str, str]]) -> list[CitationInput]:
    deduped: list[CitationInput] = []
    seen: set[str] = set()
    for item in references[:MAX_RESULTS]:
        url = item["url"]
        if url in seen:
            continue
        seen.add(url)
        citation = citation_from_item(
            {
                "url": url,
                "title": item.get("title"),
                "site_name": item.get("website"),
                "snippet": item.get("snippet"),
                "publish_time": item.get("date"),
            }
        )
        if citation is not None:
            deduped.append(citation)
    return deduped


class WenxinSearchAdapter:
    """把千帆 AI 搜索的 references 归一成 AnswerPayload。"""

    def __init__(
        self,
        db: Session,
        *,
        api_key: str,
        endpoint: str = DEFAULT_ENDPOINT,
        count: int = MAX_RESULTS,
        timeout_seconds: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._db = db
        self.api_key = api_key.strip()
        self.endpoint = endpoint.rstrip("/") or DEFAULT_ENDPOINT
        self.count = max(1, min(50, int(count)))
        self.last_request_payload: dict[str, Any] | None = None
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "WenxinSearchAdapter":
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
        body = {"messages": [{"role": "user", "content": query}]}
        self.last_request_payload = {"method": "POST", "url": self.endpoint, "body": body}
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
                f"文心搜索请求超时: {exc}",
                failure_code=FailureCode.TIMEOUT,
            ) from exc
        except httpx.HTTPError as exc:
            raise AccessBlockedFailure(f"文心搜索服务不可达: {exc}") from exc

        status = response.status_code
        if status == 429:
            raise RateLimitedFailure("文心搜索触发限流（HTTP 429）")
        if status in (401, 403):
            raise AccessBlockedFailure(f"文心搜索鉴权失败（HTTP {status}）")
        if status >= 500:
            raise TransientCollectionFailure(
                f"文心搜索服务异常（HTTP {status}）",
                failure_code=FailureCode.OTHER,
            )
        if status >= 400:
            raise CollectionFailure(
                f"文心搜索请求被拒绝（HTTP {status}）",
                failure_code=FailureCode.OTHER,
                retryable=False,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise TransientCollectionFailure(
                "文心搜索返回不是合法 JSON",
                failure_code=FailureCode.OTHER,
            ) from exc
        if not isinstance(data, dict):
            raise TransientCollectionFailure(
                "文心搜索返回结构不是 JSON 对象",
                failure_code=FailureCode.OTHER,
            )
        for key in ("error", "error_code"):
            value = data.get(key)
            if isinstance(value, dict) or (isinstance(value, str) and value.strip()):
                message = ""
                if isinstance(value, dict):
                    message = str(value.get("message") or value.get("msg") or "").strip()
                else:
                    message = str(data.get("error_msg") or "").strip()
                raise CollectionFailure(
                    f"文心搜索失败：{message or value}".strip(),
                    failure_code=FailureCode.OTHER,
                    retryable=False,
                )

        if "references" not in data:
            raise TransientCollectionFailure(
                "文心搜索返回缺少 references 字段",
                failure_code=FailureCode.OTHER,
            )

        all_references = _references(data)
        references = all_references[:MAX_RESULTS]
        return AnswerPayload(
            text=_answer_text(references),
            raw_response={
                "request_id": data.get("request_id") or data.get("id"),
                "result_count": len(references),
                "total_results": len(all_references),
                "answer_kind": "search_result",
                "references": references,
            },
            engine_model=DEFAULT_MODEL,
            model_version=DEFAULT_MODEL,
            country_code="CN",
            language="zh",
            citations=_citations(references),
        )


def build_wenxin_search_adapter(
    db: Session,
    *,
    credential_ref: str | None,
    entry_url: str | None = None,
    stored_secret: str | None = None,
    count: int = MAX_RESULTS,
    timeout_seconds: float = 60.0,
    client: httpx.Client | None = None,
) -> WenxinSearchAdapter:
    """系统内填写的密钥优先；否则从 credential_ref（默认 QIANFAN_API_KEY）读环境变量。"""
    ref = (credential_ref or "").strip() or DEFAULT_CREDENTIAL_REF
    api_key = (stored_secret or "").strip() or read_credential_env(ref)
    if not api_key:
        raise AccessBlockedFailure(f"未配置密钥（系统内填写或环境变量 {ref}），文心搜索入口无法调用")
    return WenxinSearchAdapter(
        db,
        api_key=api_key,
        endpoint=entry_url or DEFAULT_ENDPOINT,
        count=count,
        timeout_seconds=timeout_seconds,
        client=client,
    )
