"""正式 OpenAI-compatible 入口适配器。

与本地 smoke 适配器共用协议归一逻辑；区别是用于库里已启用的正式入口，
模型名、URL 和密钥引用来自 `AiEngineEntry`，不写死在代码里。

当前支持五种联网形态：
- 千帆 ModelBuilder ERNIE 对话模型：请求体顶层 `web_search: {"enable": true}`；
- 千问百炼 Chat 兼容入口：`enable_search: true` + `search_options`，仅作历史兼容；
  系统联网采集已切到 `qwen_web_search_adapter` 的 Responses `web_search`；
- 秘塔 ChatCompletions 问答：模型本身联网，引用在
  `choices[0].message.citations`（兼容 `sources` / `references`）；
- 星辰 MaaS（讯飞星火）：Chat Completions + `tools:[{"type":"web_search"}]`，
  参数按 Spark 规范使用 `max_completion_tokens`，不传 `temperature` / `max_tokens`；
- 其他普通 OpenAI 兼容入口：不加联网参数。

智谱 GLM 不走这里：`zhipu_search_adapter` 用独立 Web Search API 取来源，
再用入口配置的任意模型回答，避免把接口锁死在某一个支持内置 `web_search` 的模型上。

千帆的 `web_search` 只作用于对话端点，不是 `/v2/ai_search/web_search`
那个独立的“千帆 AI 搜索”检索产品。
千问 Chat 响应的 `search_info.search_results` 仍在这里归一成 `CitationInput`，
但该字段在真实 Chat 响应中经常不返回；新采集路径不再依赖它。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.models import MonitoringTask
from app.models.enums import AnswerKind
from app.services.engine_web_search import (
    SPARK_MAAS_HOST,
    SPARK_MAX_COMPLETION_TOKENS,
)
from app.services.local_llm_adapter import DEFAULT_SYSTEM_PROMPT, LocalLLMAdapter
from app.services.monitoring_extraction import (
    AnswerPayload,
    CitationInput,
    citation_from_item,
)


class OpenAICompatibleAdapter(LocalLLMAdapter):
    """DeepSeek、火山方舟、千帆 ERNIE、千问等 OpenAI-compatible 入口的正式适配器。"""

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
        enable_web_search: bool = False,
        web_search_mode: str | None = None,
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
        # 兼容旧调用：enable_web_search=True 默认就是千帆 ERNIE 的联网开关。
        self.web_search_mode = web_search_mode or ("qianfan" if enable_web_search else None)
        self.enable_web_search = bool(self.web_search_mode)
        # Spark 的参数约束与普通 OpenAI 兼容入口不同，按 base_url 识别即可，
        # 即使入口暂未开启 supports_search，也不会再发废弃参数。
        self.is_spark_maas = (
            (urlparse(base_url).hostname or "").casefold() == SPARK_MAAS_HOST
        )

    def _build_body(self, task: MonitoringTask) -> dict[str, Any]:
        body = super()._build_body(task)
        if self.is_spark_maas:
            # Spark 文档：temperature / top_p 固定生效、不建议传；max_tokens 已废弃。
            body.pop("temperature", None)
            body.pop("top_p", None)
            body.pop("max_tokens", None)
            body["max_completion_tokens"] = SPARK_MAX_COMPLETION_TOKENS
            body["thinking"] = {"type": "disabled"}
            if self.web_search_mode == "spark":
                body["tools"] = [
                    {
                        "type": "web_search",
                        "web_search": {"enable": True},
                    }
                ]
                body["tool_choice"] = "auto"
            return body
        if self.web_search_mode == "qianfan":
            # 只传 enable=true 时千帆会“偷偷检索”并把结果塞进 prompt（search_tokens 增长），
            # 但响应不返回 search_results，采集端看起来就是 0 引用。必须显式开引用。
            body["web_search"] = {
                "enable": True,
                "enable_citation": True,
                "enable_trace": True,
            }
        elif self.web_search_mode == "qwen":
            body["enable_search"] = True
            body["search_options"] = {
                "enable_source": True,
                "enable_citation": True,
            }
        return body

    def _collect(
        self,
        task: MonitoringTask,
        *,
        request_payload: dict[str, Any] | None,
    ) -> AnswerPayload:
        payload = super()._collect(task, request_payload=request_payload)
        if self.web_search_mode == "qianfan":
            citations = _qianfan_citations(payload.raw_response)
            if citations:
                payload.citations = citations
            if payload.answer_kind is None and payload.text.strip():
                payload.answer_kind = AnswerKind.ANSWER
            return payload
        if self.web_search_mode == "metaso":
            citations = _metaso_citations(payload.raw_response)
            if citations:
                payload.citations = citations
            if payload.answer_kind is None and payload.text.strip():
                payload.answer_kind = AnswerKind.ANSWER
            return payload
        if self.is_spark_maas:
            # Spark 返回的是生成回答，不是纯检索结果；无结构化引用，不猜 URL。
            if payload.answer_kind is None and payload.text.strip():
                payload.answer_kind = AnswerKind.ANSWER
            return payload
        if self.web_search_mode != "qwen":
            return payload

        citations = _qwen_citations(payload.raw_response)
        if citations:
            payload.citations = citations
        # 千问百炼返回的是生成回答，不是纯检索结果。
        if payload.answer_kind is None and payload.text.strip():
            payload.answer_kind = AnswerKind.ANSWER
        return payload


def _qwen_search_info(data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    info = data.get("search_info")
    if isinstance(info, dict):
        return info
    output = data.get("output")
    if isinstance(output, dict):
        nested = output.get("search_info")
        if isinstance(nested, dict):
            return nested
    return {}


def _qwen_citations(data: dict[str, Any] | None) -> list[CitationInput]:
    """千问 OpenAI 兼容响应：search_info.search_results -> CitationInput。"""
    info = _qwen_search_info(data)
    raw_results = info.get("search_results")
    if not isinstance(raw_results, list):
        return []

    citations: list[CitationInput] = []
    seen: set[str] = set()
    for item in raw_results:
        citation = citation_from_item(item)
        if citation is None or citation.url in seen:
            continue
        seen.add(citation.url)
        citations.append(citation)
    return citations


def _qianfan_citations(data: dict[str, Any] | None) -> list[CitationInput]:
    """千帆 ERNIE 联网响应：顶层 `search_results` 是引用来源。

    只在请求带 `web_search.enable_citation=true` 时返回；每项通常含
    `index` / `url` / `title`，没有摘要。缺 url 的项丢弃，不伪造引用。
    """
    if not isinstance(data, dict):
        return []
    containers: list[dict[str, Any]] = [data]
    for key in ("data", "result", "search_info"):
        nested = data.get(key)
        if isinstance(nested, dict):
            containers.append(nested)

    raw_items: list[Any] = []
    for container in containers:
        for key in ("search_results", "references", "citations", "sources"):
            value = container.get(key)
            if isinstance(value, list):
                raw_items.extend(value)

    citations: list[CitationInput] = []
    seen: set[str] = set()
    for item in raw_items:
        citation = citation_from_item(item)
        if citation is None or citation.url in seen:
            continue
        seen.add(citation.url)
        citations.append(citation)
    return citations


def _metaso_citations(data: dict[str, Any] | None) -> list[CitationInput]:
    """秘塔问答响应：真实引用在 choices[0].message.citations，兼容顶层/嵌套旧字段。"""
    if not isinstance(data, dict):
        return []
    containers: list[dict[str, Any]] = [data]
    for key in ("data", "result", "search_info"):
        nested = data.get(key)
        if isinstance(nested, dict):
            containers.append(nested)
    choices = data.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict):
            containers.append(message)
            nested = message.get("search_info")
            if isinstance(nested, dict):
                containers.append(nested)

    raw_items: list[Any] = []
    for container in containers:
        for key in ("sources", "references", "citations", "search_results", "results", "webpages"):
            value = container.get(key)
            if isinstance(value, list):
                raw_items.extend(value)

    citations: list[CitationInput] = []
    seen: set[str] = set()
    for item in raw_items:
        citation = citation_from_item(item)
        if citation is None or citation.url in seen:
            continue
        seen.add(citation.url)
        citations.append(citation)
    return citations
