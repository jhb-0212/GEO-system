"""本地 OpenAI-compatible 模型适配器（仅用于开发/链路 smoke）。

边界：
- 这不是 4 个目标 AI 平台之一，不写入正式 `ai_engines` 基线，不参与 24 格业务口径；
- 默认不支持联网搜索/引用来源，因此 `citation_share` 没有业务意义；
- 只负责把本地模型返回归一成 `AnswerPayload`，hit/miss 仍由 `apply_answer_payload` 判定；
- 服务不可达、429、超时等按现有 `CollectionFailure` 归类，不伪造回答。
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.models import MonitoringTask, QuestionVersion
from app.models.enums import FailureCode
from app.services.monitoring_collection import (
    AccessBlockedFailure,
    CollectionFailure,
    RateLimitedFailure,
    TransientCollectionFailure,
)
from app.services.monitoring_extraction import AnswerPayload, parse_raw_response

DEFAULT_SYSTEM_PROMPT = (
    "你是中文问答助手。请直接回答用户问题，信息不确定时明确说明；"
    "不要编造来源、链接或机构资质。"
)


class LocalLLMAdapter:
    """调用本地 Ollama / vLLM / LM Studio 的 OpenAI 兼容接口。"""

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
        self._db = db
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key.strip()
        self.system_prompt = system_prompt
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None
        self.last_request_payload: dict[str, Any] | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> LocalLLMAdapter:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _chat_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    def _question_text(self, task: MonitoringTask) -> str:
        version = self._db.get(QuestionVersion, task.question_version_id)
        if version is None or not version.text.strip():
            raise CollectionFailure(
                "任务关联的问题版本不存在或为空",
                failure_code=FailureCode.OTHER,
                retryable=False,
            )
        return version.text.strip()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def collect(self, task: MonitoringTask) -> AnswerPayload:
        return self._collect(task, request_payload=None)

    def collect_with_request(
        self,
        task: MonitoringTask,
        request_payload: dict[str, Any],
    ) -> AnswerPayload:
        """用留存的请求体回放；Authorization 仍从当前环境变量取，不落库。"""
        return self._collect(task, request_payload=request_payload)

    def _build_body(self, task: MonitoringTask) -> dict[str, Any]:
        question = self._question_text(task)
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": question},
            ],
            "temperature": 0.2,
            "max_tokens": 1024,
            "stream": False,
        }

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
                f"本地模型请求超时: {exc}",
                failure_code=FailureCode.TIMEOUT,
            ) from exc
        except httpx.HTTPError as exc:
            raise AccessBlockedFailure(f"本地模型服务不可达: {exc}") from exc

        if response.status_code == 429:
            raise RateLimitedFailure("本地模型触发限流（HTTP 429）")
        if response.status_code in (401, 403):
            raise AccessBlockedFailure(
                f"本地模型拒绝访问（HTTP {response.status_code}）"
            )
        if response.status_code >= 500:
            raise TransientCollectionFailure(
                f"本地模型服务异常（HTTP {response.status_code}）",
                failure_code=FailureCode.OTHER,
            )
        if response.status_code >= 400:
            raise CollectionFailure(
                f"本地模型请求被拒绝（HTTP {response.status_code}）",
                failure_code=FailureCode.OTHER,
                retryable=False,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise TransientCollectionFailure(
                "本地模型返回不是合法 JSON",
                failure_code=FailureCode.OTHER,
            ) from exc
        if not isinstance(data, dict):
            raise TransientCollectionFailure(
                "本地模型返回结构不是 JSON 对象",
                failure_code=FailureCode.OTHER,
            )

        text = _extract_text(data)
        if not text:
            raise TransientCollectionFailure(
                "本地模型返回没有可用回答文本",
                failure_code=FailureCode.OTHER,
            )

        payload = parse_raw_response(data, text=text)
        payload.engine_model = str(data.get("model") or self.model)
        payload.model_version = self.model
        payload.country_code = "CN"
        payload.language = "zh"
        return payload


def _extract_text(data: dict[str, Any]) -> str:
    """兼容 OpenAI choices[0].message.content 与常见的 content 列表。"""
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first.get("message"), dict) else {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            joined = "".join(parts).strip()
            if joined:
                return joined
    for key in ("answer", "text", "content", "output_text"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
