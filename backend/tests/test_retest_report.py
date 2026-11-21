"""P32 复测报告脚本的入口类型覆盖口径测试。"""

from scripts.export_retest_report import (
    _coverage_summary,
    _entries_by_type,
    _entry_type_verdict,
)


def test_entries_by_type_uses_live_entry_type_map():
    scope = {
        "engine_entries": [
            {"id": "api-1", "name": "API 入口"},
            {"id": "web-1", "name": "网页端入口"},
            {"id": "mapped-1", "name": "旧快照未写入类型"},
        ]
    }
    groups = _entries_by_type(
        scope,
        {"api-1": "api", "web-1": "web_user", "mapped-1": "web_user"},
    )
    assert set(groups["api"]) == {"api-1"}
    assert set(groups["web_user"]) == {"web-1", "mapped-1"}


def test_coverage_summary_keeps_api_covered_but_web_user_missing():
    covered, missing = _coverage_summary(
        baseline_entries_by_type={
            "api": {"a1": {}, "a2": {}},
            "web_user": {"w1": {}, "w2": {}},
        },
        candidate_entries_by_type={
            "api": {"a1": {}, "a2": {}},
            "web_user": {"w1": {}, "w2": {}},
        },
        baseline_tasks={"api": 12, "web_user": 12},
        candidate_tasks={"api": 12, "web_user": 12},
        baseline_samples={"api": 12, "web_user": 12},
        candidate_samples={"api": 12, "web_user": 0},
        versions_comparable=True,
        modes_comparable=True,
    )
    assert covered == ["API"]
    assert missing == ["网页用户端（未执行样本）"]


def test_coverage_summary_marks_web_user_covered_when_samples_exist():
    covered, missing = _coverage_summary(
        baseline_entries_by_type={"web_user": {"w1": {}, "w2": {}}},
        candidate_entries_by_type={"web_user": {"w1": {}, "w2": {}}},
        baseline_tasks={"web_user": 12},
        candidate_tasks={"web_user": 12},
        baseline_samples={"web_user": 12},
        candidate_samples={"web_user": 12},
        versions_comparable=True,
        modes_comparable=True,
    )
    assert covered == ["网页用户端"]
    assert missing == []


def test_entry_type_verdict_detects_entry_set_mismatch():
    verdict = _entry_type_verdict(
        baseline_entries={"w1": {}},
        candidate_entries={"w1": {}, "w2": {}},
        baseline_tasks=6,
        candidate_tasks=12,
        baseline_samples=6,
        candidate_samples=12,
        versions_comparable=True,
        modes_comparable=True,
    )
    assert verdict == "入口集合不一致"


def test_entry_type_verdict_requires_samples_across_all_tasks():
    verdict = _entry_type_verdict(
        baseline_entries={"w1": {}},
        candidate_entries={"w1": {}},
        baseline_tasks=24,
        candidate_tasks=24,
        baseline_samples=25,
        candidate_samples=1,
        versions_comparable=True,
        modes_comparable=True,
    )
    assert verdict == "样本未覆盖全部任务"
