"""Connector 协议：十个既有适配器都被登记，且都具备 fetch 层；协议不要求任何人改代码。

钉住四条：
1. 每个登记的适配器模块都能 import，且含一个实现 `collect` 的 Adapter 类；
2. `validate_connector` 对「只有 fetch 层」的对象返回空清单——这就是新引擎的最低门槛；
3. 缺 fetch 层的对象会被明确报出 `fetch`，不会静默通过；
4. probe / capability / cost 三层用默认实现，指向既有模块，不另写一套。
"""

import importlib
import inspect
import pkgutil

from app import services
from app.services import connector_protocol
from app.services.connector_protocol import (
    KNOWN_CONNECTORS,
    capability_layer,
    cost_layer,
    describe_connector,
    new_engine_checklist,
    validate_connector,
)


class _FakeConnector:
    """只实现 fetch 层的最小连接器。"""

    def __init__(self) -> None:
        self.last_request_payload = None

    def collect(self, task):
        return {"task": task}


class _Empty:
    pass


def _module_name(module_path: str) -> str:
    return "app." + module_path.removesuffix(".py").replace("/", ".")


def test_minimal_connector_passes_validation():
    fake = _FakeConnector()
    assert validate_connector(fake, engine_code="fake") == []
    profile = describe_connector(fake, engine_code="fake")
    assert profile.layers["fetch"].endswith("_FakeConnector")


def test_connector_without_collect_is_reported_missing():
    assert validate_connector(_Empty(), engine_code="empty") == ["fetch"]


def test_every_registered_connector_module_has_an_adapter_with_collect():
    for engine_code, module_path in KNOWN_CONNECTORS:
        module = importlib.import_module(_module_name(module_path))
        adapters = [
            value for name, value in vars(module).items()
            if name.endswith("Adapter") and inspect.isclass(value) and hasattr(value, "collect")
        ]
        assert adapters, f"{module_path}（{engine_code}）没有实现 collect 的 Adapter 类"


def test_registry_covers_every_adapter_module():
    """协议登记表必须覆盖真实的适配器文件，否则新引擎会被漏掉。"""
    modules = {
        f"services/{info.name}.py"
        for info in pkgutil.iter_modules(services.__path__)
        if info.name.endswith("_adapter")
    }
    registered = {path for _code, path in KNOWN_CONNECTORS}
    assert modules - registered == set(), f"以下适配器没进 KNOWN_CONNECTORS：{sorted(modules - registered)}"


def test_default_layers_point_at_existing_modules():
    assert list(inspect.signature(connector_protocol.probe_layer).parameters) == ["entry"]
    assert list(inspect.signature(capability_layer).parameters) == ["entry"]
    cost = cost_layer(input_price=1, output_price=2)
    assert cost["computed_by"] == "services/engine_gateway.py::EngineGateway"


def test_checklist_mentions_the_four_layers():
    text = "\n".join(new_engine_checklist())
    for word in ("collect", "probe", "capability", "cost"):
        assert word in text, f"清单里没说清 {word}"
