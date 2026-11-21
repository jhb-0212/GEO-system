"""千问百炼 Responses API + `web_search` 适配器。

千问 Chat Completions 的 `enable_search` 只返回生成回答，不回传
`search_info.search_results`，因此引用为 0。改用同一 Key 的
`POST /compatible-mode/v1/responses`，声明 `tools:[{"type":"web_search"}]`
后，来源在 `output[].type=web_search_call` 的 `action.sources` 中返回。

千问 Responses 与 Kimi 的差异：
- 不发送 Kimi 的 `include`、`reasoning_effort` 字段，避免传入未声明参数；
- 来源字段是 `action.sources`（通常只有 `type`/`url`，可能没有标题）；
- 搜索词是 `action.queries`，不是 `action.query`；
- `max_output_tokens` 同时覆盖思考与回答，2000 会 `incomplete`，用 16000。
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.credentials import read_credential_env
from app.models import MonitoringTask
from app.services.kimi_web_search_adapter import (
    KimiWebSearchAdapter,
    MAX_QUERY_CHARS,
)
from app.services.local_llm_adapter import DEFAULT_SYSTEM_PROMPT
from app.services.monitoring_collection import AccessBlockedFailure

DEFAULT_ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1/responses"
DEFAULT_MODEL = "qwen3.8-max"
DEFAULT_CREDENTIAL_REF = "DASHSCOPE_API_KEY"
MAX_OUTPUT_TOKENS = 16000
WEB_SEARCH_INSTRUCTION = "请优先使用联网搜索工具检索最新网页信息，并在回答中保留可追溯的来源。"


class QwenWebSearchAdapter(KimiWebSearchAdapter):
    """千问 Responses 联网入口：生成回答 + `action.sources` 引用。"""

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
    ) -> None:
        super().__init__(
            db,
            api_key=api_key,
            model=model,
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            system_prompt=system_prompt,
            client=client,
            provider_label="千问",
        )

    def _build_body(self, task: MonitoringTask) -> dict[str, Any]:
        return {
            "model": self.model,
            "instructions": f"{self.system_prompt}\n{WEB_SEARCH_INSTRUCTION}",
            "input": self._question_text(task)[:MAX_QUERY_CHARS],
            "tools": [{"type": "web_search"}],
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "stream": False,
        }


def build_qwen_web_search_adapter(
    db: Session,
    *,
    credential_ref: str | None,
    model_name: str | None,
    entry_url: str | None = None,
    stored_secret: str | None = None,
    timeout_seconds: float = 120.0,
    client: httpx.Client | None = None,
) -> QwenWebSearchAdapter:
    """系统内填写的密钥优先；否则从 credential_ref（默认 DASHSCOPE_API_KEY）读。"""
    ref = (credential_ref or "").strip() or DEFAULT_CREDENTIAL_REF
    api_key = (stored_secret or "").strip() or read_credential_env(ref)
    if not api_key:
        raise AccessBlockedFailure(
            f"未配置密钥（系统内填写或环境变量 {ref}），千问联网搜索入口无法调用"
        )
    endpoint = (entry_url or "").strip() or DEFAULT_ENDPOINT
    if not endpoint.rstrip("/").endswith("/responses"):
        endpoint = f"{endpoint.rstrip('/')}/responses"
    return QwenWebSearchAdapter(
        db,
        api_key=api_key,
        model=(model_name or "").strip() or DEFAULT_MODEL,
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
        client=client,
    )


__all__ = [
    "DEFAULT_CREDENTIAL_REF",
    "DEFAULT_ENDPOINT",
    "DEFAULT_MODEL",
    "MAX_OUTPUT_TOKENS",
    "QwenWebSearchAdapter",
    "build_qwen_web_search_adapter",
]
