"""智谱 GLM 的“独立搜索 + 任意模型回答”适配器。

设计目标：
- 入口只固定 Base URL、协议和鉴权；模型名全部从 `AiEngineEntry.model_name` 读取，
  不在代码里绑定某个具体模型；
- 每轮先调 `POST /api/paas/v4/web_search` 拿结构化来源，再把来源注入上下文，
  调 `POST /api/paas/v4/chat/completions` 让当前配置的模型回答；
- 不使用模型内置 `web_search` 工具，因此文本模型、GLM-5.3-FlashX 等模型都能走同一条链路；
- 搜索无结果、搜索余额不足、模型余额不足都按明确失败归档，不伪造回答或来源。
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.models import MonitoringTask, QuestionVersion
from app.models.enums import AnswerKind, FailureCode
from app.services.engine_web_search import (
    ZHIPU_SEARCH_CONTENT_SIZE,
    ZHIPU_SEARCH_COUNT,
    ZHIPU_SEARCH_ENGINE,
)
from app.services.local_llm_adapter import DEFAULT_SYSTEM_PROMPT, LocalLLMAdapter
from app.services.monitoring_collection import (
    AccessBlockedFailure,
    CollectionFailure,
    RateLimitedFailure,
    TransientCollectionFailure,
)
from app.services.monitoring_extraction import (
    AnswerPayload,
    CitationInput,
    citation_from_item,
    parse_raw_response,
)

ZHIPU_SEARCH_SYSTEM_PROMPT = (
    "你是中文问答助手。下面是刚刚检索到的网页资料。请优先依据这些资料回答，"
    "不要编造资料中没有的链接、数字、机构或资质；资料不足时明确说明。"
)


class ZhipuModelSearchAdapter(LocalLLMAdapter):
    """智谱 GLM：独立 Web Search API + 入口配置的任意模型。"""

    def __init__(
        self,
        db: Session,
        *,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout_seconds: float = 120.0,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(
            db,
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            system_prompt=system_prompt,
            client=client,
        )
        self.last_search_request_payload: dict[str, Any] | None = None

    def _api_base(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url[: -len("/chat/completions")]
        return self.base_url

    def _web_search_url(self) -> str:
        return f"{self._api_base()}/web_search"

    def collect(self, task: MonitoringTask) -> AnswerPayload:
        question = self._question_text(task)
        search_payload = self._search(question)
        results = search_payload.get("search_result")
        if not isinstance(results, list) or not results:
            raise CollectionFailure(
                "智谱联网搜索没有返回可用来源，拒绝生成无来源回答",
                failure_code=FailureCode.OTHER,
                retryable=False,
            )
        citations = _zhipu_search_citations(results)
        if not citations:
            raise CollectionFailure(
                "智谱联网搜索返回的来源缺少可审计 URL",
                failure_code=FailureCode.OTHER,
                retryable=False,
            )

        answer_body = self._build_answer_body(question, results)
        self.last_request_payload = answer_body
        response = self._post_json(
            self._chat_url(),
            answer_body,
            phase="模型回答",
        )
        data = _json_object(response, phase="模型回答")
        error = data.get("error")
        if isinstance(error, dict):
            _raise_business_error(error, phase="模型回答")
        text = _extract_text(data)
        if not text:
            raise TransientCollectionFailure(
                "智谱模型返回没有可用回答文本",
                failure_code=FailureCode.OTHER,
            )
        payload = parse_raw_response(data, text=text)
        payload.citations = citations
        payload.answer_kind = AnswerKind.ANSWER
        payload.engine_model = str(data.get("model") or self.model)
        payload.model_version = self.model
        payload.country_code = "CN"
        payload.language = "zh"
        return payload

    def _search(self, question: str) -> dict[str, Any]:
        # 独立搜索接口要求 query <= 70 字符；保留完整问题用于回答上下文。
        query = question[:70]
        body = {
            "search_query": query,
            "search_engine": ZHIPU_SEARCH_ENGINE,
            "search_intent": False,
            "count": ZHIPU_SEARCH_COUNT,
            "search_recency_filter": "noLimit",
            "content_size": ZHIPU_SEARCH_CONTENT_SIZE,
        }
        self.last_search_request_payload = body
        response = self._post_json(
            self._web_search_url(),
            body,
            phase="联网搜索",
        )
        data = _json_object(response, phase="联网搜索")
        error = data.get("error")
        if isinstance(error, dict):
            _raise_business_error(error, phase="联网搜索")
        return data

    def _build_answer_body(
        self,
        question: str,
        results: list[Any],
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": ZHIPU_SEARCH_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"问题：{question}\n\n"
                        f"搜索结果：\n{_format_search_results(results)}"
                    ),
                },
            ],
            "temperature": 0.2,
            "max_tokens": 4096,
            "stream": False,
        }

    def _post_json(
        self,
        url: str,
        body: dict[str, Any],
        *,
        phase: str,
    ) -> httpx.Response:
        try:
            response = self._client.post(
                url,
                headers=self._headers(),
                content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            )
        except httpx.TimeoutException as exc:
            raise TransientCollectionFailure(
                f"智谱{phase}请求超时: {exc}",
                failure_code=FailureCode.TIMEOUT,
            ) from exc
        except httpx.HTTPError as exc:
            raise AccessBlockedFailure(f"智谱{phase}服务不可达: {exc}") from exc

        if response.status_code == 429:
            error = _error_body(response)
            code = str(error.get("code") or "")
            detail = str(error.get("message") or "").strip()
            if code == "1113" or "余额不足" in detail or "资源包" in detail:
                raise AccessBlockedFailure(
                    f"智谱{phase}余额不足或无可用资源包"
                    f"（{code or '429'}）：{detail or '请充值'}"
                )
            raise RateLimitedFailure(f"智谱{phase}触发限流（HTTP 429）")
        if response.status_code in (401, 403):
            raise AccessBlockedFailure(
                f"智谱{phase}拒绝访问（HTTP {response.status_code}）"
            )
        if response.status_code >= 500:
            raise TransientCollectionFailure(
                f"智谱{phase}服务异常（HTTP {response.status_code}）",
                failure_code=FailureCode.OTHER,
            )
        if response.status_code >= 400:
            error = _error_body(response)
            detail = str(error.get("message") or "").strip()
            raise CollectionFailure(
                f"智谱{phase}请求被拒绝（HTTP {response.status_code}）"
                f"{'：' + detail if detail else ''}",
                failure_code=FailureCode.OTHER,
                retryable=False,
            )
        return response


def _error_body(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    error = data.get("error")
    if isinstance(error, dict):
        return error
    return data


def _json_object(response: httpx.Response, *, phase: str) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise TransientCollectionFailure(
            f"智谱{phase}返回不是合法 JSON",
            failure_code=FailureCode.OTHER,
        ) from exc
    if not isinstance(data, dict):
        raise TransientCollectionFailure(
            f"智谱{phase}返回结构不是 JSON 对象",
            failure_code=FailureCode.OTHER,
        )
    return data


def _raise_business_error(error: dict[str, Any], *, phase: str) -> None:
    code = str(error.get("code") or "")
    detail = str(error.get("message") or "").strip()
    if code == "1113" or "余额不足" in detail or "资源包" in detail:
        raise AccessBlockedFailure(
            f"智谱{phase}余额不足或无可用资源包"
            f"（{code or 'unknown'}）：{detail or '请充值'}"
        )
    raise CollectionFailure(
        f"智谱{phase}业务错误 {code or 'unknown'}：{detail}",
        failure_code=FailureCode.OTHER,
        retryable=False,
    )


def _extract_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    return content.strip() if isinstance(content, str) else ""


def _format_search_results(results: list[Any]) -> str:
    lines: list[str] = []
    for index, item in enumerate(results, 1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        link = str(item.get("link") or "").strip()
        media = str(item.get("media") or "").strip()
        publish_date = str(item.get("publish_date") or "").strip()
        content = str(item.get("content") or "").strip()
        lines.append(
            f"[ref_{index}] 标题：{title or '无'}\n"
            f"站点：{media or '未知'}\n"
            f"发布时间：{publish_date or '未知'}\n"
            f"URL：{link or '无'}\n"
            f"摘要：{content[:800] or '无'}"
        )
    return "\n\n".join(lines)


def _zhipu_search_citations(results: list[Any]) -> list[CitationInput]:
    citations: list[CitationInput] = []
    seen: set[str] = set()
    for item in results:
        citation = citation_from_item(item)
        if citation is None or citation.url in seen:
            continue
        seen.add(citation.url)
        citations.append(citation)
    return citations
