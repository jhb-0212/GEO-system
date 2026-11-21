"""OpenAI-compatible 入口的厂商联网能力判定。

这些入口在库里仍统一记为 `openai_compatible`，因为它们的鉴权与消息形态
都是 OpenAI 风格；差异只在联网开关和响应字段。把 host 判定集中在这里，
避免采集适配器与连通性探针各写一份、后续漂移。
"""

from __future__ import annotations

from urllib.parse import urlparse

from app.models import AiEngineEntry

KIMI_HOSTS = {"api.moonshot.cn", "api.moonshot.ai"}
QWEN_HOSTS = {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com"}
QIANFAN_HOST = "qianfan.baidubce.com"
SPARK_MAAS_HOST = "maas-api.cn-huabei-1.xf-yun.com"
SPARK_MAX_COMPLETION_TOKENS = 1024
METASO_HOST = "metaso.cn"
ZHIPU_HOSTS = {"open.bigmodel.cn", "api.z.ai"}
ZHIPU_SEARCH_ENGINE = "search_pro"
ZHIPU_SEARCH_COUNT = 10
ZHIPU_SEARCH_CONTENT_SIZE = "high"
QIHU360_HOST = "api.360.cn"
QIHU360_SEARCH_PATHS = {"/v1/search", "/v1/search/aisearch"}


def is_qihu360_ai_search_entry(entry: AiEngineEntry) -> bool:
    """360 智脑 AI 搜索入口：`/v1/search/aisearch` 返回回答 + references。"""
    return (
        bool(getattr(entry, "supports_search", False))
        and _host(entry) == QIHU360_HOST
        and _path(entry) in QIHU360_SEARCH_PATHS
    )


def is_metaso_web_search_entry(entry: AiEngineEntry) -> bool:
    """秘塔的 ChatCompletions 问答本身走联网检索，入口基址固定为 /api/v1。"""
    return (
        bool(getattr(entry, "supports_search", False))
        and _host(entry) == METASO_HOST
        and _path(entry) in {"/api/v1", "/api/v1/chat/completions"}
    )


def is_zhipu_web_search_entry(entry: AiEngineEntry) -> bool:
    """智谱 GLM 联网入口：两段式独立搜索 + 入口 model_name 回答。

    入口地址保持 PaaS v4 根路径，适配器负责补 `/web_search` 与
    `/chat/completions`；也兼容已经填完整 Chat 路径的入口。只按 host/path
    与 supports_search 判定，不按模型名判定。
    """
    return (
        bool(getattr(entry, "supports_search", False))
        and _host(entry) in ZHIPU_HOSTS
        and _path(entry) in {
            "/api/paas/v4",
            "/api/paas/v4/chat/completions",
        }
    )


def _host(entry: AiEngineEntry) -> str:
    return (urlparse(entry.entry_url or "").hostname or "").casefold()


def _path(entry: AiEngineEntry) -> str:
    return (urlparse(entry.entry_url or "").path.rstrip("/") or "/")


def is_kimi_web_search_entry(entry: AiEngineEntry) -> bool:
    """Kimi 只有显式打开 supports_search 时才走 Responses 的 web_search。"""
    return bool(getattr(entry, "supports_search", False)) and _host(entry) in KIMI_HOSTS


def is_qwen_web_search_entry(entry: AiEngineEntry) -> bool:
    """千问百炼联网入口：改走 Responses `web_search`，从 `action.sources` 取引用。

    入口 URL 仍保存 `/compatible-mode/v1` 基址，适配器负责追加 `/responses`。
    """
    return (
        bool(getattr(entry, "supports_search", False))
        and _host(entry) in QWEN_HOSTS
        and _path(entry).startswith("/compatible-mode")
    )


def is_qianfan_model_web_search_entry(entry: AiEngineEntry) -> bool:
    """千帆 ERNIE 对话模型的联网开关；独立 AI 搜索产品不适用。"""
    return (
        bool(getattr(entry, "supports_search", False))
        and _host(entry) == QIANFAN_HOST
        and _path(entry) in {"/v2", "/v2/chat/completions"}
    )


def is_spark_maas_entry(entry: AiEngineEntry) -> bool:
    """星辰 MaaS 的 OpenAI Chat 入口，地址基址为 /v2 或完整 /v2/chat/completions。"""
    return _host(entry) == SPARK_MAAS_HOST and _path(entry) in {
        "/v2",
        "/v2/chat/completions",
    }


def is_spark_web_search_entry(entry: AiEngineEntry) -> bool:
    """星辰 MaaS 在 supports_search=true 时走 tools=[{type:web_search}]。"""
    return bool(getattr(entry, "supports_search", False)) and is_spark_maas_entry(entry)
