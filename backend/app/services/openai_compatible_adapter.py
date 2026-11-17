"""正式 OpenAI-compatible 入口适配器。

与本地 smoke 适配器共用协议归一逻辑；区别是用于库里已启用的正式入口，
模型名、URL 和密钥引用来自 `AiEngineEntry`，不写死在代码里。

千帆 ModelBuilder 的 ERNIE 对话模型走本协议；需要联网时由入口的
`supports_search` 打开请求体顶层 `web_search: {"enable": true}`。这不是
`/v2/ai_search/web_search` 那个独立的“千帆 AI 搜索”检索产品。
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.models import MonitoringTask
from app.services.local_llm_adapter import DEFAULT_SYSTEM_PROMPT, LocalLLMAdapter


class OpenAICompatibleAdapter(LocalLLMAdapter):
    """DeepSeek、火山方舟、千帆 ERNIE 等 OpenAI-compatible 入口的正式适配器。"""

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
        self.enable_web_search = enable_web_search

    def _build_body(self, task: MonitoringTask) -> dict[str, Any]:
        body = super()._build_body(task)
        if self.enable_web_search:
            body["web_search"] = {"enable": True}
        return body
