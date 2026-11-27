from __future__ import annotations

import importlib.util
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND_DIR / "scripts" / "seed_r2_r3_test_data.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("seed_r2_r3_test_data", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_round_plan_is_two_synthetic_rounds():
    module = _load_module()
    assert len(module.ROUNDS) == 2
    for spec in module.ROUNDS:
        assert "测试数据" in spec["name"]
        assert "合成" in spec["name"]
        assert spec["planned_at"].tzinfo is not None


def test_round_hits_stay_within_six_questions_and_four_engines():
    module = _load_module()
    allowed_questions = {"Q01", "Q02", "Q03", "Q04", "Q05", "Q06"}
    for spec in module.ROUNDS:
        assert set(spec["hits"]).issubset(allowed_questions)
        for engine_codes in spec["hits"].values():
            assert engine_codes.issubset(set(module.ENGINES))


def test_synthetic_hit_totals_are_7_and_6():
    module = _load_module()
    totals = [sum(len(codes) for codes in spec["hits"].values()) for spec in module.ROUNDS]
    assert totals == [7, 6]
