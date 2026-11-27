from __future__ import annotations

import importlib.util
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND_DIR / "scripts" / "seed_user_side_entries.py"

EXPECTED = {
    "baidu_ai_search",
    "deepseek",
    "doubao",
    "kimi",
    "metaso",
    "nami_ai",
    "qianwen",
    "quark",
    "spark",
    "wechat_search_ai",
    "wenxin",
    "xiaohongshu_diandian",
    "yuanbao",
    "zhihu_direct",
    "zhipu",
}


def _load_plan():
    spec = importlib.util.spec_from_file_location("seed_user_side_entries", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PLAN


def test_plan_covers_all_15_engines():
    plan = _load_plan()
    assert set(plan) == EXPECTED
    assert len(plan) == 15


def test_each_engine_has_web_and_app_manual_entry():
    plan = _load_plan()
    for code, spec in plan.items():
        assert set(spec) == {"web", "app"}, code
        for kind in ("web", "app"):
            name, url, note = spec[kind]
            assert name and len(name) <= 64, (code, kind, name)
            assert note and len(note) >= 10, (code, kind)
            if kind == "web":
                assert url and url.startswith("https://"), (code, url)
            else:
                assert url is None, (code, kind)
        assert spec["web"][0] != spec["app"][0], code


def test_wechat_web_is_placeholder_not_collectable():
    plan = _load_plan()
    name, url, note = plan["wechat_search_ai"]["web"]
    assert url == "https://search.weixin.qq.com/"
    assert "无独立网页版" in note
    assert "强制停用" in note
