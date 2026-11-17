"""基线轮次导入脚本的纯函数级回归：状态校验与 baseline 语义。"""

import uuid

import pytest

from scripts.import_baseline_round import plan_import


def _source(*, status="completed", is_baseline=True):
    return {
        "project": {"code": "gz-base", "name": "广州基地"},
        "round": {
            "id": uuid.uuid4(),
            "name": "测试轮次",
            "status": status,
            "is_baseline": is_baseline,
        },
        "tasks": [{
            "id": uuid.uuid4(),
            "question_code": "Q01",
            "version_no": 1,
            "engine_code": "deepseek_web_search",
            "sampling_no": 1,
            "sampling_mode": "search_on",
            "status": "done",
            "planned_at": None,
            "created_at": None,
            "updated_at": None,
            "trace_id": None,
        }],
    }


def _target(*, with_baseline=False):
    baseline_id = uuid.uuid4()
    return {
        "qv_map": {("Q01", 1): uuid.uuid4()},
        "entry_map": {"deepseek_web_search": [uuid.uuid4()]},
        "rounds": ([{"id": baseline_id, "seq": 1, "is_baseline": True}]
                   if with_baseline else []),
    }


def test_plan_rejects_non_completed_source():
    with pytest.raises(SystemExit, match="只允许导入 completed"):
        plan_import(_source(status="running"), _target(), replace_baseline=False)


def test_plan_rejects_non_baseline_without_opt_in():
    with pytest.raises(SystemExit, match="不是 baseline"):
        plan_import(_source(is_baseline=False), _target(), replace_baseline=False)


def test_plan_allows_historical_round_without_becoming_baseline():
    target = _target(with_baseline=True)
    plan = plan_import(
        _source(is_baseline=False),
        target,
        replace_baseline=False,
        allow_non_baseline=True,
    )
    assert plan["is_baseline"] is False
    assert plan["baseline_to_close"] is None


def test_plan_rejects_baseline_conflict_without_replace():
    with pytest.raises(SystemExit, match="已有 baseline"):
        plan_import(_source(), _target(with_baseline=True), replace_baseline=False)


def test_plan_replaces_old_baseline_when_explicit():
    target = _target(with_baseline=True)
    plan = plan_import(_source(), target, replace_baseline=True)
    assert plan["is_baseline"] is True
    assert plan["baseline_to_close"] == target["rounds"][0]["id"]


def test_plan_rejects_missing_target_question_version():
    target = _target()
    target["qv_map"].clear()
    with pytest.raises(SystemExit, match="缺少题目版本"):
        plan_import(_source(), target, replace_baseline=False)
