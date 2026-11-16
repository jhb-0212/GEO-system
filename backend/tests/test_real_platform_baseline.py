"""真实平台基线脚本的 --only 参数与配置筛选测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.real_platform_baseline import _load_platforms, _parse_only


def test_parse_only_keeps_platform_order() -> None:
    assert _parse_only("wenxin,deepseek") == ("deepseek", "wenxin")


def test_parse_only_rejects_unknown_platform() -> None:
    with pytest.raises(SystemExit, match="未知平台"):
        _parse_only("deepseek,unknown")


def test_load_platforms_only_reads_selected(tmp_path: Path) -> None:
    payload = {
        "deepseek": {"engine_code": "deepseek"},
        "doubao": {"engine_code": "doubao"},
        "wenxin": {"engine_code": "wenxin"},
        "yuanbao": {"engine_code": "yuanbao"},
    }
    config = tmp_path / "platforms.json"
    config.write_text(json.dumps(payload), encoding="utf-8")

    loaded = _load_platforms(config, ("deepseek", "wenxin"))

    assert list(loaded) == ["deepseek", "wenxin"]
    assert loaded["wenxin"]["engine_code"] == "wenxin"
