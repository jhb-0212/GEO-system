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
body: model + tools:[{"type":"web_search"}] + input
resp: output[]（reasoning / web_search_call / message），usage.tool_usage.web_search

来源与两个版本（官方文档 2026-11-16 更新，实测 2026-11-17 复核）：
- `sources:["doubao"]` 是**豆包搜索 Custom 版**，需要先在控制台「应用组件库 > 豆包搜索」开通服务；
  未开通时返回 `403 AccessDenied for web search`。不是参数写错，是组件没开。
- 不传 `sources` 走**联网内容插件**，默认来源 `search_engine`（通用全网搜索），
  可附加 `douyin`（抖音百科）/`toutiao`（头条图文）/`moji`（墨迹天气）。
- **口径含义**：走 `search_engine` 时，结果不是“字节系生态内容”。
  `raw_response["search_sources"]` 会记下本轮实际用了哪些来源及次数。

可测性口径（固定下来才可比）：
- `limit`：单轮搜索返回的最大结果条数，1–50，**默认 10**；只对联网内容插件生效
  （`sources=["doubao"]` 时被忽略）。它**不封顶引用总数**——单轮可能多次搜索，
  实测 `limit=10` + 3 次搜索 → 11 条 annotation / 9 条去重。
- `max_tool_calls`：一次响应内工具调用轮次上限，1–10，**默认 3**。总引用规模主要由它控制，
  所以显式下发，不让默认值漂移。
- `store` 显式 `false`：监测用途不需要在方舟侧留存响应体。
- 来源归因取 `usage.tool_usage_details.web_search`（按来源计数），
  **不要**从 `web_search_call.action` 里找 `source`——该字段实测不存在。
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
DEFAULT_SOURCES: tuple[str, ...] = ()
# 每轮最大检索结果数，文档允许 1–50、默认 10。写死是为了让口径不随默认值漂移。
DEFAULT_LIMIT = 10
LIMIT_MIN, LIMIT_MAX = 1, 50
# 单次回答输出上限。Lite 的思考 token 也计入 max_output_tokens，1024 会在
# 思考后直接截断（incomplete_details.reason=length），4096 才够“思考 + 回答”。
DEFAULT_MAX_OUTPUT_TOKENS = 4096
# 一次响应内工具调用轮次上限，文档允许 1–10、默认 3。它才决定引用总量。
DEFAULT_MAX_TOOL_CALLS = 3
MAX_TOOL_CALLS_MIN, MAX_TOOL_CALLS_MAX = 1, 10
# 方舟在模型未开通/模型 ID 不存在时返回 404，这类属于配置/权限问题，不是重试能解决的。
MODEL_NOT_OPEN_CODES = {"ModelNotOpen", "InvalidEndpointOrModel.NotFound", "ModelNotFound"}


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


def _search_sources(data: dict[str, Any]) -> dict[str, int]:
    """按来源统计联网搜索次数，取 `usage.tool_usage_details.web_search`。

    文档口径：`tool_usage_details` 给出每个搜索源的调用次数（`search_engine` /
    `doubao` / `toutiao` / `douyin` / `moji`）。这是唯一可靠的来源归因位；
    `web_search_call.action` 里只有 `type`/`query`，没有 `source`（实测）。
    """
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return {}
    details = usage.get("tool_usage_details")
    if not isinstance(details, dict):
        return {}
    web = details.get("web_search")
    if not isinstance(web, dict):
        return {}
    counts: dict[str, int] = {}
    for source, value in web.items():
        name = str(source or "").strip()
        if not name:
            continue
        try:
            counts[name] = int(value)
        except (TypeError, ValueError):
            continue
    return counts


def _search_calls_detail(data: dict[str, Any]) -> list[dict[str, str]]:
    """逐次记录 web_search_call 的 query 与 source（toutiao / douyin / moji 等）。

    保留 `action.source` 是为了在被引用内容的来源归因里留住“字节系”这一层；
    文档里该字段只在部分来源出现，缺失时记空串而不是丢弃整条。
    """
    output = data.get("output")
    if not isinstance(output, list):
        return []
    detail: list[dict[str, str]] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "web_search_call":
            continue
        action = item.get("action")
        if not isinstance(action, dict):
            continue
        queries: list[str] = []
        for key in ("query", "queries"):
            value = action.get(key)
            if isinstance(value, str) and value.strip():
                queries.append(value.strip())
            elif isinstance(value, list):
                for entry in value:
                    if isinstance(entry, str) and entry.strip():
                        queries.append(entry.strip())
        source = str(action.get("source") or "").strip()
        for query in dict.fromkeys(queries):
            detail.append({"query": query, "source": source})
        if not queries:
            detail.append({"query": "", "source": source})
    return detail


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
        limit: int = DEFAULT_LIMIT,
        max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        timeout_seconds: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._db = db
        self.api_key = api_key.strip()
        self.model = model
        self.endpoint = endpoint.rstrip("/") or DEFAULT_ENDPOINT
        self.sources = tuple(sources) or DEFAULT_SOURCES
        if not LIMIT_MIN <= int(limit) <= LIMIT_MAX:
            raise ValueError(
                f"limit 必须落在 {LIMIT_MIN}–{LIMIT_MAX}（文档取值区间），收到 {limit}"
            )
        if not MAX_TOOL_CALLS_MIN <= int(max_tool_calls) <= MAX_TOOL_CALLS_MAX:
            raise ValueError(
                "max_tool_calls 必须落在 "
                f"{MAX_TOOL_CALLS_MIN}–{MAX_TOOL_CALLS_MAX}（文档取值区间），收到 {max_tool_calls}"
            )
        self.limit = int(limit)
        self.max_tool_calls = int(max_tool_calls)
        self.max_output_tokens = int(max_output_tokens)
        self.last_request_payload: dict[str, Any] | None = None
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None

    @property
    def search_scope(self) -> str:
        """请求侧限定的来源：未限定=`search_engine`，否则写出来源列表。"""
        return ",".join(self.sources) if self.sources else "search_engine"

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
        tool: dict[str, Any] = {"type": "web_search", "limit": self.limit}
        if self.sources:
            tool["sources"] = list(self.sources)
        return {
            "model": self.model,
            "tools": [tool],
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": self._question_text(task)}],
                }
            ],
            "stream": False,
            # 输出上限：不设会让模型按默认生成长答案，单次可拖到 120 秒超时。
            "max_output_tokens": self.max_output_tokens,
            # 显式下发轮次上限：默认 3，但它决定引用总量，不能让默认值悄悄漂移
            "max_tool_calls": self.max_tool_calls,
            # 显式不留存：监测用途不需要方舟侧保存响应体。
            "store": False,
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
        # 老请求体没带 store 时补成 false，避免回放又在方舟侧留存一份。
        body.setdefault("store", False)
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
            blocked_code, blocked_message = _error_detail(response)
            if blocked_code == "AccessDenied" and "web search" in blocked_message.lower():
                raise AccessBlockedFailure(
                    f"豆包联网搜索未开通（{blocked_code}）：{blocked_message}；"
                    "请到火山方舟控制台确认联网搜索的激活状态后重试"
                )
            raise AccessBlockedFailure(f"豆包搜索鉴权失败（HTTP {status}）")
        if status >= 500:
            raise TransientCollectionFailure(
                f"豆包搜索服务异常（HTTP {status}）",
                failure_code=FailureCode.OTHER,
            )
        if status >= 400:
            blocked_code, blocked_message = _error_detail(response)
            if blocked_code in MODEL_NOT_OPEN_CODES:
                raise AccessBlockedFailure(
                    f"豆包搜索模型未开通（{blocked_code}）：{blocked_message}；"
                    "请到火山方舟控制台开通该模型服务后重试"
                )
            detail = " ".join(part for part in (blocked_code, blocked_message) if part)
            raise CollectionFailure(
                f"豆包搜索请求被拒绝（HTTP {status}）{(' ' + detail) if detail else ''}",
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
        citations = _citations(data)
        calls_detail = _search_calls_detail(data)
        source_counts = _search_sources(data)
        call_count = len(
            [
                1
                for item in (data.get("output") or [])
                if isinstance(item, dict) and item.get("type") == "web_search_call"
            ]
        )
        return AnswerPayload(
            text=text,
            raw_response={
                "response_id": data.get("id"),
                "model": data.get("model"),
                "status": data.get("status"),
                "answer_kind": "answer",
                "search_queries": _search_calls(data),
                # 逐次检索的关键词（action 里只有 type/query，没有 source）
                "search_calls": calls_detail,
                # 来源归因看这里：{"search_engine": 9} / {"doubao": 1} / {"toutiao": 2}
                "search_sources": source_counts,
                "search_source_names": sorted(source_counts.keys()),
                # search_engine = 通用搜索引擎（未限定字节系来源），别读成豆包生态曝光
                "search_scope": self.search_scope,
                "search_limit": self.limit,
                "max_tool_calls": self.max_tool_calls,
                "web_search_calls": call_count,
                "citation_count": len(citations),
                "usage": usage,
                "output": data.get("output"),
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


def build_doubao_search_adapter(
    db: Session,
    *,
    credential_ref: str | None,
    model_name: str | None,
    entry_url: str | None = None,
    limit: int = DEFAULT_LIMIT,
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    timeout_seconds: float = 120.0,
    client: httpx.Client | None = None,
) -> DoubaoSearchAdapter:
    """从 credential_ref（默认 ARK_API_KEY）读 key；模型名取入口配置。

    `limit` / `max_tool_calls` 默认写死为文档默认值，改它等于改口径：
    引用条数的分母会跟着变，历史轮次就不再可比。真要改，应作为新口径同时记录进文档。
    """
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
        limit=limit,
        max_tool_calls=max_tool_calls,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
        client=client,
    )
