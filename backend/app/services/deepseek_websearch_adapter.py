"""DeepSeek 网页版联网搜索（chat.deepseek.com「智能搜索」）适配器。

边界：
- DeepSeek 官方 API 没有联网搜索能力（`supports_search=false`），要拿 DeepSeek 自己的
  检索行为与引用来源，只能走网页端；本适配器不自己开浏览器，而是调用本地采集桥
  （`backend/scripts/deepseek_websearch_bridge.py`），由桥用持久化登录的浏览器采集。
- 适配器只发 httpx 请求，不接触登录信息；桥的登录态由人工在桥启动时完成一次。
- 失败严格分类：桥不可达/鉴权失败 → `access_blocked`；网页端未登录 → `login_blocked`；
  超时 → `timeout`；限流 → `rate_limited`。任何分支都不伪造回答。
- 输出口径是「DeepSeek 联网检索 + 生成回答」，带 citations；样本 `engine_model` 固定
  `deepseek-websearch`，不与 openai_compatible 入口的「回答提及」口径混算。
"""

from __future__ import annotations

import os
import re
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
from app.services.monitoring_extraction import AnswerPayload, CitationInput

DEFAULT_MODEL = "deepseek-websearch"
COLLECT_PATH = "/collect"
HEALTH_PATH = "/health"
# 页面把引用编号渲染成 "-\\n9"；入库前规范成 [9]，与前端展示一致。
_CITATION_MARK_RE = re.compile(r"-\n(\d+)\s*")


class LoginBlockedFailure(CollectionFailure):
    """网页端未登录：可人工登录后重跑，不自动重试、不计入有效未命中。"""

    def __init__(self, message: str = "DeepSeek 网页版未登录，请先在采集桥完成登录") -> None:
        super().__init__(message, failure_code=FailureCode.LOGIN_BLOCKED, retryable=False)


def _normalize_answer(text: str) -> str:
    cleaned = _CITATION_MARK_RE.sub(r"[\1]", str(text or ""))
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    return cleaned.strip()


def _parse_citations(raw: Any) -> list[CitationInput]:
    result: list[CitationInput] = []
    seen: set[str] = set()
    if not isinstance(raw, list):
        return result
    for item in raw:
        url = ""
        if isinstance(item, str):
            url = item.strip()
        elif isinstance(item, dict):
            url = str(item.get("url") or item.get("link") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(CitationInput(url=url))
    return result


class DeepSeekWebsearchAdapter:
    """把采集桥返回的回答与引用归一成监测样本可用的 AnswerPayload。"""

    def __init__(
        self,
        db: Session,
        *,
        bridge_url: str,
        token: str = "",
        timeout_seconds: float = 180.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._db = db
        self.bridge_url = bridge_url.rstrip("/")
        self.token = token.strip()
        self.timeout_seconds = timeout_seconds
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None
        self.last_request_payload: dict[str, Any] | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "DeepSeekWebsearchAdapter":
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

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def health(self) -> dict[str, Any]:
        """桥健康与登录态；接入页/排障页用它判断“能不能跑”，不创建样本。"""
        try:
            response = self._client.get(
                f"{self.bridge_url}{HEALTH_PATH}",
                headers=self._headers(),
            )
        except httpx.TimeoutException as exc:
            raise TransientCollectionFailure(
                f"采集桥健康检查超时: {exc}",
                failure_code=FailureCode.TIMEOUT,
            ) from exc
        except httpx.HTTPError as exc:
            raise AccessBlockedFailure(f"采集桥不可达: {exc}") from exc
        if response.status_code >= 400:
            raise AccessBlockedFailure(
                f"采集桥健康检查被拒绝（HTTP {response.status_code}）"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise TransientCollectionFailure(
                "采集桥健康检查返回不是合法 JSON",
                failure_code=FailureCode.OTHER,
            ) from exc

    def _raise_for_error_body(self, status: int, body: Any) -> None:
        """桥用 409 + error=login_required 表达未登录，用 401/403 表达桥鉴权失败。"""
        error = ""
        message = ""
        if isinstance(body, dict):
            error = str(body.get("error") or "").strip()
            message = str(body.get("message") or "").strip()
        if status in (401, 403) and error != "login_required":
            raise AccessBlockedFailure(
                f"采集桥鉴权失败（HTTP {status}）{message}".strip()
            )
        if status == 409 and error == "login_required":
            raise LoginBlockedFailure(message or "DeepSeek 网页版未登录")
        if status == 429:
            raise RateLimitedFailure(f"采集桥限流（HTTP 429）{message}".strip())
        if status == 504:
            raise TransientCollectionFailure(
                f"采集桥等待回答超时{('：' + message) if message else ''}",
                failure_code=FailureCode.TIMEOUT,
            )
        if status >= 500:
            raise TransientCollectionFailure(
                f"采集桥服务异常（HTTP {status}）{message}".strip(),
                failure_code=FailureCode.OTHER,
            )
        raise CollectionFailure(
            f"采集桥拒绝请求（HTTP {status}）{message}".strip(),
            failure_code=FailureCode.OTHER,
            retryable=False,
        )

    def _collect(self, question: str) -> AnswerPayload:
        self.last_request_payload = {
            "question": question,
            "bridge_url": self.bridge_url,
            "engine": DEFAULT_MODEL,
        }
        body = {"question": question, "timeout_seconds": int(self.timeout_seconds)}
        try:
            response = self._client.post(
                f"{self.bridge_url}{COLLECT_PATH}",
                headers=self._headers(),
                json=body,
            )
        except httpx.TimeoutException as exc:
            raise TransientCollectionFailure(
                f"采集桥请求超时: {exc}",
                failure_code=FailureCode.TIMEOUT,
            ) from exc
        except httpx.HTTPError as exc:
            raise AccessBlockedFailure(f"采集桥不可达: {exc}") from exc

        data: Any = None
        try:
            data = response.json()
        except ValueError:
            data = None
        if response.status_code >= 400:
            self._raise_for_error_body(response.status_code, data)
        if not isinstance(data, dict):
            raise TransientCollectionFailure(
                "采集桥返回不是 JSON 对象",
                failure_code=FailureCode.OTHER,
            )
        if data.get("logged_in") is False:
            raise LoginBlockedFailure(
                str(data.get("message") or "DeepSeek 网页版未登录")
            )

        answer = _normalize_answer(data.get("answer") or "")
        if not answer:
            raise CollectionFailure(
                "采集桥返回空回答；未落 hit/miss",
                failure_code=FailureCode.OTHER,
                retryable=False,
            )
        return AnswerPayload(
            text=answer,
            raw_response={
                "engine": DEFAULT_MODEL,
                "question": question,
                "session_url": data.get("session_url"),
                "searched_page_count": data.get("searched_page_count"),
                "logged_in": data.get("logged_in"),
                "citations": data.get("citations") or [],
                "elapsed_ms": data.get("elapsed_ms"),
            },
            engine_model=DEFAULT_MODEL,
            model_version=data.get("model_name") or DEFAULT_MODEL,
            country_code="CN",
            language="zh",
            citations=_parse_citations(data.get("citations")),
        )

    def collect(self, task: MonitoringTask) -> AnswerPayload:
        return self._collect(self._question_text(task))

    def collect_with_request(
        self,
        task: MonitoringTask,
        request_payload: dict[str, Any],
    ) -> AnswerPayload:
        """回放：优先用样本留存的原始问法，避免“换题重跑”被当成回放。"""
        question = ""
        if isinstance(request_payload, dict):
            question = str(request_payload.get("question") or "").strip()
        if not question:
            question = self._question_text(task)
        return self._collect(question)


def build_deepseek_websearch_adapter(
    db: Session,
    *,
    entry_url: str | None,
    credential_ref: str | None = None,
    bridge_url_fallback: str = "",
    timeout_seconds: float = 180.0,
    client: httpx.Client | None = None,
) -> DeepSeekWebsearchAdapter:
    """入口 entry_url 为采集桥地址；未填时回落到 `DEEPSEEK_WEBSEARCH_BRIDGE_URL`。

    桥可选地要求 Bearer Token：credential_ref 只存环境变量名，不落明文。
    """
    bridge_url = (entry_url or "").strip() or bridge_url_fallback.strip()
    if not bridge_url:
        raise AccessBlockedFailure(
            "deepseek_websearch 入口未配置 entry_url，且未设置 DEEPSEEK_WEBSEARCH_BRIDGE_URL"
        )
    token = ""
    if credential_ref:
        token = os.getenv(credential_ref, "").strip()
        if not token:
            raise AccessBlockedFailure(f"环境变量 {credential_ref} 未配置（采集桥 Token）")
    return DeepSeekWebsearchAdapter(
        db,
        bridge_url=bridge_url,
        token=token,
        timeout_seconds=timeout_seconds,
        client=client,
    )
