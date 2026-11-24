"""Connector 协议：把「接一个引擎」拆成四层显式接口，新增引擎只需实现 fetch 层。

现状是四个概念叠在四个文件里，边界靠注释维持，加一个引擎要动 3–4 处：
- `engine_connectors.py`  连通性诊断（发探针，不存正文）
- `engine_gateway.py`     统一结果、重试、fallback、耗时/token/费用、trace
- `engine_web_search.py`  厂商「联网能力」判定（哪种入口真的能搜）
- `*_search_adapter.py`   实际采集（豆包 / DeepSeek / 千问 / 文心 / 元宝 / Kimi / 智谱 / 360）

这四层本身都对，问题是它们之间没有契约。本模块只做三件事：
1. 定义 `Connector` 协议与四层契约（probe / capability / fetch / cost）；
2. 给现有实现提供默认适配（`ProbeLayer` / `CapabilityLayer` / `GatewayLayer`），
   让新引擎可以只实现 `fetch` 一层就接进来；
3. 提供 `validate_connector()` 与 `describe_connector()`，把「缺哪层」变成可测断言，
   而不是靠人读注释。

设计边界：
- **不改现有调用路径**：这里没有替换任何既有代码，采集仍然走原来的适配器与网关；
- 不引入插件发现机制、不扫描目录、不做动态加载——注册仍是显式代码；
- 不在协议里放厂商细节（URL、鉴权、参数拼装都留在适配器内部）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

CONNECTOR_VERSION = "connector_protocol_v1"

# 四层契约。新增引擎至少要填 fetch 层，其余三层可以用默认实现。
REQUIRED_LAYERS = ("fetch",)
OPTIONAL_LAYERS = ("probe", "capability", "cost")


@dataclass
class ConnectorProfile:
    """一个引擎连接器的自述：它是什么、哪层由谁实现、成本怎么算。"""

    engine_code: str
    label: str = ""
    layers: dict[str, str] = field(default_factory=dict)
    notes: str = ""

    def missing_layers(self) -> list[str]:
        return [layer for layer in REQUIRED_LAYERS if layer not in self.layers]


@runtime_checkable
class Connector(Protocol):
    """采集层契约：一个连接器必须能「取一次回答」。

    `collect` 返回 `AnswerPayload`（`services/monitoring_extraction.py`）；
    需要回放留存请求体时实现 `collect_with_request`，否则网关会回落到 `collect`。
    """

    def collect(self, task: Any) -> Any: ...


def has_fetch_layer(adapter: Any) -> bool:
    return callable(getattr(adapter, "collect", None))


def describe_connector(adapter: Any, *, engine_code: str) -> ConnectorProfile:
    """从既有适配器对象读出它实际提供了哪几层。

    这里刻意用「探测属性」而不是要求适配器继承基类：现有八个适配器都不必改动。
    """
    layers: dict[str, str] = {}
    if has_fetch_layer(adapter):
        layers["fetch"] = f"{type(adapter).__module__}.{type(adapter).__name__}"
    if callable(getattr(adapter, "collect_with_request", None)):
        layers["fetch+replay"] = "collect_with_request"
    if getattr(adapter, "last_request_payload", None) is not None or hasattr(adapter, "last_request_payload"):
        layers["cost"] = "gateway 按 token 估算（services/engine_gateway.py）"
    return ConnectorProfile(engine_code=engine_code, layers=layers)


def validate_connector(adapter: Any, *, engine_code: str) -> list[str]:
    """返回缺层清单；空列表表示可以接进采集链路。"""
    return describe_connector(adapter, engine_code=engine_code).missing_layers()


def probe_layer(entry: Any) -> dict:
    """默认 probe 实现：直接复用既有连通性诊断，不复制探针逻辑。"""
    from app.services.engine_connectors import test_entry_connection

    return test_entry_connection(entry)


def capability_layer(entry: Any) -> dict[str, bool]:
    """默认 capability 实现：把既有的「哪个入口真能搜」判定收成一个字典。"""
    from app.services import engine_web_search

    checks = {
        "qihu360": engine_web_search.is_qihu360_ai_search_entry,
        "metaso": engine_web_search.is_metaso_web_search_entry,
        "zhipu": engine_web_search.is_zhipu_web_search_entry,
        "kimi": engine_web_search.is_kimi_web_search_entry,
        "qwen": engine_web_search.is_qwen_web_search_entry,
        "qianfan_model": engine_web_search.is_qianfan_model_web_search_entry,
        "spark_maas": engine_web_search.is_spark_maas_entry,
        "spark_web_search": engine_web_search.is_spark_web_search_entry,
    }
    return {name: check(entry) for name, check in checks.items()}


def cost_layer(*, input_price: Any, output_price: Any) -> dict[str, Any]:
    """默认 cost 实现：单价交给 `EngineGateway` 计算，不在这里另算一套。"""
    return {
        "input_price_cny_per_million": input_price,
        "output_price_cny_per_million": output_price,
        "computed_by": "services/engine_gateway.py::EngineGateway",
    }


# 显式注册表：新增引擎在这里加一行，不在协议里做目录扫描。
# 路径用于测试断言「每个采集适配器都被登记过」，也当新引擎的对照清单用。
KNOWN_CONNECTORS: tuple[tuple[str, str], ...] = (
    ("doubao", "services/doubao_search_adapter.py"),
    ("deepseek", "services/deepseek_web_search_adapter.py"),
    ("qwen", "services/qwen_web_search_adapter.py"),
    ("wenxin", "services/wenxin_search_adapter.py"),
    ("yuanbao", "services/yuanbao_search_adapter.py"),
    ("kimi", "services/kimi_web_search_adapter.py"),
    ("zhipu", "services/zhipu_search_adapter.py"),
    ("qihu360", "services/qihu360_search_adapter.py"),
    # 通用兜底：本地模型 / OpenAI 兼容端点，同样按四层契约接入
    ("local_llm", "services/local_llm_adapter.py"),
    ("openai_compatible", "services/openai_compatible_adapter.py"),
)


def new_engine_checklist() -> list[str]:
    """接一个新引擎时照这个清单走；任何时候都能当文档用。"""
    return [
        "1. 写 services/<engine>_search_adapter.py，实现 collect(task) -> AnswerPayload",
        "2. 在 KNOWN_CONNECTORS 里登记一行（引擎 code + 适配器路径）",
        "3. 若厂商入口需要判定「哪个能真搜」，在 engine_web_search.py 加一个 is_*_entry",
        "4. 若厂商需要连通性诊断，在 engine_connectors.py 加一个 _test_*_entry",
        "5. probe / capability / cost 三层用本模块默认实现即可，不必重复写",
    ]
