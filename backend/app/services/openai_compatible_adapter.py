"""正式 OpenAI-compatible 入口适配器。

与本地 smoke 适配器共用协议归一逻辑；区别是用于库里已启用的正式入口，
模型名、URL 和密钥引用来自 `AiEngineEntry`，不写死在代码里。
"""

from __future__ import annotations

from app.services.local_llm_adapter import LocalLLMAdapter


class OpenAICompatibleAdapter(LocalLLMAdapter):
    """DeepSeek、火山方舟等 OpenAI-compatible 入口的正式适配器。"""
