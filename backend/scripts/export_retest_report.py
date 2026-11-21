"""生成同题同引擎同模式复测报告（P32）。

两种模式：
1. 指标对比（默认）：读取两轮已冻结的 `stat_snapshots`，按入口类型分别判断
   API / web_user 是否可比；不把 API 结论外推到网页端。
2. 覆盖预检（`--coverage-only`）：复测轮次尚未产生样本/快照时，只核对轮次、
   入口、题目、任务与样本覆盖，明确“还差什么”，不计算指标。

所有指标只来自冻结快照，样本/任务数量另查任务与样本表，只用于说明边界。
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    AiEngine,
    AiEngineEntry,
    EvidenceFile,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Project,
    Question,
    QuestionVersion,
    StatSnapshot,
)

DEFAULT_PROJECT_ID = uuid.UUID("154640d4-6356-4a1c-8bde-2d511cfb06cd")
DEFAULT_BASELINE_ROUND = uuid.UUID("b01c5f7b-0aa3-48e6-b422-789a7ba4702e")
DEFAULT_CANDIDATE_ROUND = uuid.UUID("26ca0939-c87c-403a-a6d9-e6624d9e4711")
CST = ZoneInfo("Asia/Shanghai")

ENTRY_TYPE_LABELS = {
    "api": "API",
    "web_user": "网页用户端",
    "app_user": "客户端",
    "app_search": "应用内搜索",
    "unknown": "未知",
}
ENTRY_TYPE_ORDER = ("api", "web_user", "app_user", "app_search", "unknown")


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.2f}%"


def _pp(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:+.2f}pp"


def _fmt_time(value: object) -> str:
    if not value:
        return "—"
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CST)
    return parsed.astimezone(CST).strftime("%Y-%m-%d %H:%M")


def _cell(value: object) -> str:
    return str(value or "—").replace("|", "\\|").replace("\n", " ")


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _entry_type_label(value: str) -> str:
    return ENTRY_TYPE_LABELS.get(value, value)


def _type_sort_key(value: str) -> tuple[int, str]:
    try:
        return (ENTRY_TYPE_ORDER.index(value), value)
    except ValueError:
        return (len(ENTRY_TYPE_ORDER), value)


def _sample_count(overview: dict) -> int:
    excluded = overview.get("excluded") or {}
    return int(overview.get("valid_answers") or 0) + sum(
        int(excluded.get(key) or 0)
        for key in ("failed", "manual_review", "no_answer_surface", "pending_or_running")
    )


def _engine_rows(snapshot: StatSnapshot) -> list[dict]:
    return list((snapshot.metrics or {}).get("by_engine") or [])


def _entries_by_type(scope: dict, type_by_id: dict[str, str]) -> dict[str, dict[str, dict]]:
    groups: dict[str, dict[str, dict]] = {}
    for item in scope.get("engine_entries") or []:
        entry_id = str(item.get("id") or "")
        if not entry_id:
            continue
        entry_type = type_by_id.get(entry_id) or str(item.get("entry_type") or "unknown")
        groups.setdefault(entry_type, {})[entry_id] = item
    return groups


def _version_map(scope: dict) -> dict[str, dict]:
    return {str(item.get("id")): item for item in scope.get("question_versions") or []}


def _entry_type_verdict(
    *,
    baseline_entries: dict[str, dict],
    candidate_entries: dict[str, dict],
    baseline_tasks: int,
    candidate_tasks: int,
    baseline_samples: int,
    candidate_samples: int,
    versions_comparable: bool,
    modes_comparable: bool,
) -> str:
    if not baseline_entries and not candidate_entries:
        return "两侧都没有该入口类型"
    if not baseline_entries:
        return "仅复测侧存在"
    if not candidate_entries:
        return "仅基线侧存在"
    if set(baseline_entries) != set(candidate_entries):
        return "入口集合不一致"
    if baseline_tasks == 0 or candidate_tasks == 0:
        return "任务未建齐"
    if baseline_samples == 0 or candidate_samples == 0:
        return "未执行样本"
    if baseline_samples < baseline_tasks or candidate_samples < candidate_tasks:
        return "样本未覆盖全部任务"
    if not versions_comparable:
        return "题目版本不一致"
    if not modes_comparable:
        return "采样模式不一致"
    return "可比"


def _coverage_summary(
    *,
    baseline_entries_by_type: dict[str, dict[str, dict]],
    candidate_entries_by_type: dict[str, dict[str, dict]],
    baseline_tasks: dict,
    candidate_tasks: dict,
    baseline_samples: dict,
    candidate_samples: dict,
    versions_comparable: bool,
    modes_comparable: bool,
) -> tuple[list[str], list[str]]:
    covered: list[str] = []
    missing: list[str] = []
    for entry_type in sorted(
        set(baseline_entries_by_type) | set(candidate_entries_by_type),
        key=_type_sort_key,
    ):
        verdict = _entry_type_verdict(
            baseline_entries=baseline_entries_by_type.get(entry_type, {}),
            candidate_entries=candidate_entries_by_type.get(entry_type, {}),
            baseline_tasks=int(baseline_tasks.get(entry_type, 0)),
            candidate_tasks=int(candidate_tasks.get(entry_type, 0)),
            baseline_samples=int(baseline_samples.get(entry_type, 0)),
            candidate_samples=int(candidate_samples.get(entry_type, 0)),
            versions_comparable=versions_comparable,
            modes_comparable=modes_comparable,
        )
        if verdict == "可比":
            covered.append(_entry_type_label(entry_type))
        else:
            missing.append(f"{_entry_type_label(entry_type)}（{verdict}）")
    return covered, missing


def build_markdown(
    *,
    project: Project,
    baseline_round: MonitoringRound,
    candidate_round: MonitoringRound,
    baseline: StatSnapshot,
    candidate: StatSnapshot,
    baseline_tasks: dict,
    candidate_tasks: dict,
    baseline_samples: dict,
    candidate_samples: dict,
    entry_type_by_id: dict[str, str],
) -> str:
    b_scope = baseline.scope or {}
    c_scope = candidate.scope or {}
    b_metrics = baseline.metrics or {}
    c_metrics = candidate.metrics or {}
    b_over = b_metrics.get("overview") or {}
    c_over = c_metrics.get("overview") or {}
    b_engines = _engine_rows(baseline)
    c_engines = _engine_rows(candidate)
    engine_names = {
        row["engine_code"]: row["engine_name"] for row in b_engines + c_engines
    }

    b_versions = _version_map(b_scope)
    c_versions = _version_map(c_scope)
    common_versions = set(b_versions) & set(c_versions)
    versions_comparable = (
        len(common_versions) == len(b_versions) == len(c_versions) and bool(common_versions)
    )
    b_modes = sorted(b_scope.get("sampling_modes") or [])
    c_modes = sorted(c_scope.get("sampling_modes") or [])
    modes_comparable = b_modes == c_modes and bool(b_modes)

    b_entries_by_type = _entries_by_type(b_scope, entry_type_by_id)
    c_entries_by_type = _entries_by_type(c_scope, entry_type_by_id)

    b_samples = _sample_count(b_over)
    c_samples = _sample_count(c_over)
    deltas: dict[str, float | None] = {
        "mention": (c_over.get("brand_mention_rate") or 0) - (b_over.get("brand_mention_rate") or 0),
        "identified": (c_over.get("brand_identified_rate") or 0) - (b_over.get("brand_identified_rate") or 0),
        "citation": (c_over.get("citation_rate") or 0) - (b_over.get("citation_rate") or 0),
    }
    covered_types, missing_types = _coverage_summary(
        baseline_entries_by_type=b_entries_by_type,
        candidate_entries_by_type=c_entries_by_type,
        baseline_tasks=baseline_tasks,
        candidate_tasks=candidate_tasks,
        baseline_samples=baseline_samples,
        candidate_samples=candidate_samples,
        versions_comparable=versions_comparable,
        modes_comparable=modes_comparable,
    )

    lines: list[str] = []
    add = lines.append
    add(f"# {project.name} P32 同题同引擎同模式复测报告")
    add("")
    add(
        f"> 对比对象：seq{baseline_round.seq}「{_cell(baseline_round.name)}」"
        f" vs seq{candidate_round.seq}「{_cell(candidate_round.name)}」。"
    )
    add("> 指标全部来自两轮已冻结的 `stat_snapshots`；样本/任务覆盖另查任务与样本表，只用于说明边界。")
    add("")
    add("## 0. 快照与轮次")
    add("")
    add("| 项 | 基线 | 复测 |")
    add("|---|---|---|")
    add(f"| 轮次名称 | {_cell(baseline_round.name)} | {_cell(candidate_round.name)} |")
    add(f"| 轮次状态 | `{_enum_value(baseline_round.status)}` | `{_enum_value(candidate_round.status)}` |")
    add(f"| 是否基线 | {'是' if baseline_round.is_baseline else '否'} | {'是' if candidate_round.is_baseline else '否'} |")
    add(f"| 快照 ID | `{baseline.id}` | `{candidate.id}` |")
    add(f"| 快照 hash | `{baseline.snapshot_hash}` | `{candidate.snapshot_hash}` |")
    add(f"| 冻结时间 | {_fmt_time(baseline.captured_at)} | {_fmt_time(candidate.captured_at)} |")
    add(f"| 规则版本 | `{baseline.rule_version}` | `{candidate.rule_version}` |")
    add("")

    add("## 1. 按入口类型的覆盖与可比性")
    add("")
    add("| 入口类型 | 基线入口 | 复测入口 | 共同入口 | 基线任务/样本 | 复测任务/样本 | 判定 |")
    add("|---|---:|---:|---:|---:|---:|---|")
    for entry_type in sorted(
        set(b_entries_by_type) | set(c_entries_by_type),
        key=_type_sort_key,
    ):
        b_group = b_entries_by_type.get(entry_type, {})
        c_group = c_entries_by_type.get(entry_type, {})
        common = set(b_group) & set(c_group)
        verdict = _entry_type_verdict(
            baseline_entries=b_group,
            candidate_entries=c_group,
            baseline_tasks=int(baseline_tasks.get(entry_type, 0)),
            candidate_tasks=int(candidate_tasks.get(entry_type, 0)),
            baseline_samples=int(baseline_samples.get(entry_type, 0)),
            candidate_samples=int(candidate_samples.get(entry_type, 0)),
            versions_comparable=versions_comparable,
            modes_comparable=modes_comparable,
        )
        add(
            f"| {_entry_type_label(entry_type)} | {len(b_group)} | {len(c_group)} | "
            f"{len(common)} | {int(baseline_tasks.get(entry_type, 0))}/"
            f"{int(baseline_samples.get(entry_type, 0))} | "
            f"{int(candidate_tasks.get(entry_type, 0))}/"
            f"{int(candidate_samples.get(entry_type, 0))} | {verdict} |"
        )
    add("")
    add(
        f"题目版本：共同 {len(common_versions)} / 基线 {len(b_versions)} / 复测 {len(c_versions)}；"
        f"采样模式：基线 {', '.join(b_modes) or '—'} / 复测 {', '.join(c_modes) or '—'}。"
    )
    add("")

    add("## 2. 核心指标对比")
    add("")
    add("| 指标 | 基线 | 复测 | 差值 |")
    add("|---|---:|---:|---:|")
    add(f"| 总样本（有效+排除） | {b_samples} | {c_samples} | {c_samples - b_samples:+d} |")
    add(f"| 有效回答 | {int(b_over.get('valid_answers') or 0)} | {int(c_over.get('valid_answers') or 0)} | {int(c_over.get('valid_answers') or 0) - int(b_over.get('valid_answers') or 0):+d} |")
    add(f"| 失败样本 | {int((b_over.get('excluded') or {}).get('failed') or 0)} | {int((c_over.get('excluded') or {}).get('failed') or 0)} | {int((c_over.get('excluded') or {}).get('failed') or 0) - int((b_over.get('excluded') or {}).get('failed') or 0):+d} |")
    add(f"| 品牌提及回答 | {int(b_over.get('brand_mentioned_answers') or 0)} | {int(c_over.get('brand_mentioned_answers') or 0)} | {int(c_over.get('brand_mentioned_answers') or 0) - int(b_over.get('brand_mentioned_answers') or 0):+d} |")
    add(f"| 品牌提及率 | {_pct(b_over.get('brand_mention_rate'))} | {_pct(c_over.get('brand_mention_rate'))} | {_pp(deltas['mention'])} |")
    add(f"| 品牌识别回答 | {int(b_over.get('brand_identified_answers') or 0)} | {int(c_over.get('brand_identified_answers') or 0)} | {int(c_over.get('brand_identified_answers') or 0) - int(b_over.get('brand_identified_answers') or 0):+d} |")
    add(f"| 品牌识别率 | {_pct(b_over.get('brand_identified_rate'))} | {_pct(c_over.get('brand_identified_rate'))} | {_pp(deltas['identified'])} |")
    add(f"| 引用回答 | {int(b_over.get('citation_answers') or 0)} | {int(c_over.get('citation_answers') or 0)} | {int(c_over.get('citation_answers') or 0) - int(b_over.get('citation_answers') or 0):+d} |")
    add(f"| 引用率 | {_pct(b_over.get('citation_rate'))} | {_pct(c_over.get('citation_rate'))} | {_pp(deltas['citation'])} |")
    add(f"| 渠道数 | {int(b_over.get('channel_count') or 0)} | {int(c_over.get('channel_count') or 0)} | {int(c_over.get('channel_count') or 0) - int(b_over.get('channel_count') or 0):+d} |")
    add("")
    add(
        f"解释：品牌提及率变化 **{_pp(deltas['mention'])}**，来自有效回答 "
        f"{int(b_over.get('valid_answers') or 0)}→{int(c_over.get('valid_answers') or 0)} 条、"
        f"提及回答 {int(b_over.get('brand_mentioned_answers') or 0)}→"
        f"{int(c_over.get('brand_mentioned_answers') or 0)} 条；绝对样本仍很小，不能据此断言内容优化生效。"
    )
    add("")

    add("## 3. 分引擎对比（合并入口类型）")
    add("")
    add("| 引擎 | 基线有效/提及 | 基线提及率 | 复测有效/提及 | 复测提及率 | 有效差值 | 提及率差值 |")
    add("|---|---:|---:|---:|---:|---:|---:|")
    for code in sorted(set(row["engine_code"] for row in b_engines) | set(row["engine_code"] for row in c_engines)):
        b = next((row for row in b_engines if row["engine_code"] == code), {})
        c = next((row for row in c_engines if row["engine_code"] == code), {})
        name = engine_names.get(code, code)
        b_valid = int(b.get("valid_answers") or 0)
        c_valid = int(c.get("valid_answers") or 0)
        b_men = int(b.get("brand_mentioned_answers") or 0)
        c_men = int(c.get("brand_mentioned_answers") or 0)
        add(
            f"| {_cell(name)} | {b_valid}/{b_men} | {_pct(b.get('brand_mention_rate'))} | "
            f"{c_valid}/{c_men} | {_pct(c.get('brand_mention_rate'))} | {c_valid - b_valid:+d} | "
            f"{_pp((c.get('brand_mention_rate') or 0) - (b.get('brand_mention_rate') or 0))} |"
        )
    add("")
    add("分引擎仍是小样本：单引擎样本量很小时，任一单条样本都会造成大幅跳动；只用于定位下一步复测重点，不作为效果排名。")
    add("")

    add("## 4. 结论与边界")
    add("")
    if covered_types:
        add(f"- **已覆盖且可比**：{', '.join(covered_types)}。")
    else:
        add("- **已覆盖且可比**：无。")
    if missing_types:
        add(f"- **未覆盖/不可比**：{'; '.join(missing_types)}。")
    else:
        add("- **未覆盖/不可比**：无。")
    add(
        "- **不能推断**：品牌提及率变化是内容、时间还是样本波动导致的；"
        "本报告只记录差值，不做因果结论。"
    )
    if any("网页用户端" in item for item in missing_types):
        add("- **下一步**：必须补 `web_user` 的真实人工采样；不能拿 API 结果替代网页端。")
    else:
        add("- **下一步**：按入口类型分别复核样本构成，再决定是否进入首月结论。")
    add("")

    add("## 5. 复验入口")
    add("")
    add("```powershell")
    add("docker exec geo-postgres psql -U geo -d geo -P pager=off \\")
    add(
        f"  -c \"select id, round_id, captured_at, snapshot_hash from stat_snapshots "
        f"where round_id in ('{baseline.round_id}','{candidate.round_id}');\""
    )
    add("```")
    add("")
    return "\n".join(lines)


def build_coverage_markdown(
    *,
    project: Project,
    baseline_round: MonitoringRound,
    candidate_round: MonitoringRound,
    baseline_tasks: dict,
    candidate_tasks: dict,
    baseline_samples: dict,
    candidate_samples: dict,
    baseline_evidence_samples: int,
    candidate_evidence_samples: int,
    baseline_entries_by_type: dict[str, dict[str, dict]],
    candidate_entries_by_type: dict[str, dict[str, dict]],
    baseline_versions: dict[str, dict],
    candidate_versions: dict[str, dict],
    baseline_modes: list[str],
    candidate_modes: list[str],
) -> str:
    common_versions = set(baseline_versions) & set(candidate_versions)
    versions_comparable = (
        len(common_versions) == len(baseline_versions) == len(candidate_versions)
        and bool(common_versions)
    )
    modes_comparable = baseline_modes == candidate_modes and bool(baseline_modes)
    covered_types, missing_types = _coverage_summary(
        baseline_entries_by_type=baseline_entries_by_type,
        candidate_entries_by_type=candidate_entries_by_type,
        baseline_tasks=baseline_tasks,
        candidate_tasks=candidate_tasks,
        baseline_samples=baseline_samples,
        candidate_samples=candidate_samples,
        versions_comparable=versions_comparable,
        modes_comparable=modes_comparable,
    )

    lines: list[str] = []
    add = lines.append
    add(f"# {project.name} P32 网页端同题复测覆盖预检")
    add("")
    add("> 本报告只核对覆盖，不计算指标；复测轮次尚未执行样本时使用。")
    add("")
    add("## 0. 轮次")
    add("")
    add("| 项 | 基线 | 复测 |")
    add("|---|---|---|")
    add(f"| 轮次 | seq{baseline_round.seq}「{_cell(baseline_round.name)}」 | seq{candidate_round.seq}「{_cell(candidate_round.name)}」 |")
    add(f"| 状态 | `{_enum_value(baseline_round.status)}` | `{_enum_value(candidate_round.status)}` |")
    add(f"| 是否基线 | {'是' if baseline_round.is_baseline else '否'} | {'是' if candidate_round.is_baseline else '否'} |")
    add("")
    add("## 1. 入口与样本覆盖")
    add("")
    add("| 入口类型 | 基线入口 | 复测入口 | 共同入口 | 基线任务/样本 | 复测任务/样本 | 判定 |")
    add("|---|---:|---:|---:|---:|---:|---|")
    for entry_type in sorted(
        set(baseline_entries_by_type) | set(candidate_entries_by_type),
        key=_type_sort_key,
    ):
        b_group = baseline_entries_by_type.get(entry_type, {})
        c_group = candidate_entries_by_type.get(entry_type, {})
        common = set(b_group) & set(c_group)
        verdict = _entry_type_verdict(
            baseline_entries=b_group,
            candidate_entries=c_group,
            baseline_tasks=int(baseline_tasks.get(entry_type, 0)),
            candidate_tasks=int(candidate_tasks.get(entry_type, 0)),
            baseline_samples=int(baseline_samples.get(entry_type, 0)),
            candidate_samples=int(candidate_samples.get(entry_type, 0)),
            versions_comparable=versions_comparable,
            modes_comparable=modes_comparable,
        )
        add(
            f"| {_entry_type_label(entry_type)} | {len(b_group)} | {len(c_group)} | "
            f"{len(common)} | {int(baseline_tasks.get(entry_type, 0))}/"
            f"{int(baseline_samples.get(entry_type, 0))} | "
            f"{int(candidate_tasks.get(entry_type, 0))}/"
            f"{int(candidate_samples.get(entry_type, 0))} | {verdict} |"
        )
    add("")
    add(
        f"题目版本：共同 {len(common_versions)} / 基线 {len(baseline_versions)} / 复测 {len(candidate_versions)}；"
        f"采样模式：基线 {', '.join(baseline_modes) or '—'} / 复测 {', '.join(candidate_modes) or '—'}。"
    )
    add("")
    add("## 2. 题目清单")
    add("")
    add("| 题目 | 基线版本 | 复测版本 | 是否共同 |")
    add("|---|---|---|---|")
    for version_id in sorted(
        set(baseline_versions) | set(candidate_versions),
        key=lambda value: str((baseline_versions.get(value) or candidate_versions.get(value) or {}).get("question_code", value)),
    ):
        b = baseline_versions.get(version_id, {})
        c = candidate_versions.get(version_id, {})
        code = b.get("question_code") or c.get("question_code") or "—"
        add(f"| {_cell(code)} | {_cell(b.get('version_no') or '—')} | {_cell(c.get('version_no') or '—')} | {'是' if version_id in common_versions else '否'} |")
    add("")
    add("## 3. 结论")
    add("")
    if covered_types:
        add(f"- 已覆盖且可比：{', '.join(covered_types)}。")
    else:
        add("- 已覆盖且可比：无。")
    if missing_types:
        add(f"- 未覆盖/不可比：{'; '.join(missing_types)}。")
    else:
        add("- 未覆盖/不可比：无。")
    add(f"- 复测任务 {sum(int(value) for value in candidate_tasks.values())} 条，样本 {sum(int(value) for value in candidate_samples.values())} 条。")
    add(
        f"- 证据样本：基线 {baseline_evidence_samples} / 复测 {candidate_evidence_samples}；"
        "复测侧每条样本必须至少挂 1 个证据后才能进入验收。"
    )
    add("- 只有实际完成人工采样并留下证据后，才能冻结快照、比较指标；覆盖预检不等于复测完成。")
    add("")
    return "\n".join(lines)


def _task_sample_counts(db, project_id: uuid.UUID, round_id: uuid.UUID):
    task_rows = db.execute(
        select(AiEngineEntry.entry_type, func.count(MonitoringTask.id))
        .join(MonitoringTask, MonitoringTask.engine_entry_id == AiEngineEntry.id)
        .where(
            MonitoringTask.project_id == project_id,
            MonitoringTask.round_id == round_id,
        )
        .group_by(AiEngineEntry.entry_type)
    ).all()
    sample_rows = db.execute(
        select(AiEngineEntry.entry_type, func.count(MonitoringSample.id))
        .join(MonitoringTask, MonitoringTask.engine_entry_id == AiEngineEntry.id)
        .join(MonitoringSample, MonitoringSample.task_id == MonitoringTask.id)
        .where(
            MonitoringTask.project_id == project_id,
            MonitoringTask.round_id == round_id,
        )
        .group_by(AiEngineEntry.entry_type)
    ).all()
    return (
        {_enum_value(entry_type): int(count) for entry_type, count in task_rows},
        {_enum_value(entry_type): int(count) for entry_type, count in sample_rows},
    )


def _entry_type_by_id(db, scope_list: list[dict], project_id: uuid.UUID, round_ids: list[uuid.UUID]) -> dict[str, str]:
    ids = {
        str(item.get("id"))
        for scope in scope_list
        for item in scope.get("engine_entries") or []
        if item.get("id")
    }
    if not ids:
        rows = db.execute(
            select(AiEngineEntry.id, AiEngineEntry.entry_type)
            .join(MonitoringTask, MonitoringTask.engine_entry_id == AiEngineEntry.id)
            .where(
                MonitoringTask.project_id == project_id,
                MonitoringTask.round_id.in_(round_ids),
            )
            .distinct()
        ).all()
        return {str(entry_id): _enum_value(entry_type) for entry_id, entry_type in rows}
    rows = db.execute(
        select(AiEngineEntry.id, AiEngineEntry.entry_type).where(
            AiEngineEntry.id.in_([uuid.UUID(item) for item in ids])
        )
    ).all()
    return {str(entry_id): _enum_value(entry_type) for entry_id, entry_type in rows}


def _round_scope_from_tasks(db, project_id: uuid.UUID, round_id: uuid.UUID) -> dict:
    question_rows = db.execute(
        select(QuestionVersion, Question)
        .join(Question, Question.id == QuestionVersion.question_id)
        .join(MonitoringTask, MonitoringTask.question_version_id == QuestionVersion.id)
        .where(
            MonitoringTask.project_id == project_id,
            MonitoringTask.round_id == round_id,
        )
        .distinct()
    ).all()
    entries = db.execute(
        select(AiEngineEntry.id, AiEngineEntry.name, AiEngineEntry.entry_type, AiEngine.code, AiEngine.name)
        .join(AiEngine, AiEngine.id == AiEngineEntry.engine_id)
        .join(MonitoringTask, MonitoringTask.engine_entry_id == AiEngineEntry.id)
        .where(
            MonitoringTask.project_id == project_id,
            MonitoringTask.round_id == round_id,
        )
        .distinct()
    ).all()
    modes = db.scalars(
        select(MonitoringTask.sampling_mode)
        .where(
            MonitoringTask.project_id == project_id,
            MonitoringTask.round_id == round_id,
        )
        .distinct()
    ).all()
    return {
        "engine_entries": [
            {
                "id": str(entry_id),
                "name": entry_name,
                "entry_type": _enum_value(entry_type),
                "engine_code": engine_code,
                "engine_name": engine_name,
            }
            for entry_id, entry_name, entry_type, engine_code, engine_name in entries
        ],
        "question_versions": [
            {
                "id": str(version.id),
                "version_no": version.version_no,
                "question_code": question.code,
                "question_title": question.title,
                "question_type": _enum_value(question.question_type),
                "text": version.text,
            }
            for version, question in question_rows
        ],
        "sampling_modes": [_enum_value(mode) for mode in modes],
    }


def _samples_with_evidence(db, project_id: uuid.UUID, round_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count(func.distinct(MonitoringSample.id)))
            .select_from(MonitoringSample)
            .join(MonitoringTask, MonitoringTask.id == MonitoringSample.task_id)
            .join(EvidenceFile, EvidenceFile.sample_id == MonitoringSample.id)
            .where(
                MonitoringSample.project_id == project_id,
                MonitoringTask.round_id == round_id,
            )
        )
        or 0
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", default=str(DEFAULT_PROJECT_ID))
    parser.add_argument("--baseline-round", default=str(DEFAULT_BASELINE_ROUND))
    parser.add_argument("--candidate-round", default=str(DEFAULT_CANDIDATE_ROUND))
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--coverage-only",
        action="store_true",
        help="只生成覆盖预检，不要求复测轮次已有冻结快照",
    )
    args = parser.parse_args()

    project_id = uuid.UUID(args.project_id)
    baseline_round_id = uuid.UUID(args.baseline_round)
    candidate_round_id = uuid.UUID(args.candidate_round)
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        if project is None:
            raise SystemExit(f"项目不存在: {project_id}")
        baseline_round = db.get(MonitoringRound, baseline_round_id)
        candidate_round = db.get(MonitoringRound, candidate_round_id)
        if baseline_round is None or candidate_round is None:
            raise SystemExit("轮次不存在")
        baseline_tasks, baseline_samples = _task_sample_counts(db, project_id, baseline_round_id)
        candidate_tasks, candidate_samples = _task_sample_counts(db, project_id, candidate_round_id)

        if args.coverage_only:
            baseline_scope = _round_scope_from_tasks(db, project_id, baseline_round_id)
            candidate_scope = _round_scope_from_tasks(db, project_id, candidate_round_id)
            entry_type_map = _entry_type_by_id(
                db,
                [baseline_scope, candidate_scope],
                project_id,
                [baseline_round_id, candidate_round_id],
            )
            markdown = build_coverage_markdown(
                project=project,
                baseline_round=baseline_round,
                candidate_round=candidate_round,
                baseline_tasks=baseline_tasks,
                candidate_tasks=candidate_tasks,
                baseline_samples=baseline_samples,
                candidate_samples=candidate_samples,
                baseline_evidence_samples=_samples_with_evidence(db, project_id, baseline_round_id),
                candidate_evidence_samples=_samples_with_evidence(db, project_id, candidate_round_id),
                baseline_entries_by_type=_entries_by_type(baseline_scope, entry_type_map),
                candidate_entries_by_type=_entries_by_type(candidate_scope, entry_type_map),
                baseline_versions=_version_map(baseline_scope),
                candidate_versions=_version_map(candidate_scope),
                baseline_modes=sorted(baseline_scope.get("sampling_modes") or []),
                candidate_modes=sorted(candidate_scope.get("sampling_modes") or []),
            )
        else:
            baseline = db.scalar(
                select(StatSnapshot).where(
                    StatSnapshot.project_id == project_id,
                    StatSnapshot.round_id == baseline_round_id,
                )
            )
            candidate = db.scalar(
                select(StatSnapshot).where(
                    StatSnapshot.project_id == project_id,
                    StatSnapshot.round_id == candidate_round_id,
                )
            )
            if baseline is None or candidate is None:
                raise SystemExit("缺少轮次冻结快照；请先调用 create_round_snapshot，或使用 --coverage-only")
            entry_type_map = _entry_type_by_id(
                db,
                [baseline.scope or {}, candidate.scope or {}],
                project_id,
                [baseline_round_id, candidate_round_id],
            )
            markdown = build_markdown(
                project=project,
                baseline_round=baseline_round,
                candidate_round=candidate_round,
                baseline=baseline,
                candidate=candidate,
                baseline_tasks=baseline_tasks,
                candidate_tasks=candidate_tasks,
                baseline_samples=baseline_samples,
                candidate_samples=candidate_samples,
                entry_type_by_id=entry_type_map,
            )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    print(f"written: {output} ({len(markdown)} bytes)")


if __name__ == "__main__":
    main()
