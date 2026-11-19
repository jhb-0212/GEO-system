"""从 seq3/seq4 冻结快照生成同题同引擎同模式复测报告（P32）。

只使用 `stat_snapshots` 中已冻结的 scope/metrics，样本数量另查任务/样本表用于
说明覆盖边界；不重新计算指标，避免报告与快照漂移。
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
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Project,
    StatSnapshot,
)

DEFAULT_PROJECT_ID = uuid.UUID("154640d4-6356-4a1c-8bde-2d511cfb06cd")
DEFAULT_BASELINE_ROUND = uuid.UUID("b01c5f7b-0aa3-48e6-b422-789a7ba4702e")
DEFAULT_CANDIDATE_ROUND = uuid.UUID("26ca0939-c87c-403a-a6d9-e6624d9e4711")
CST = ZoneInfo("Asia/Shanghai")


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


def _sample_count(overview: dict) -> int:
    excluded = overview.get("excluded") or {}
    return int(overview.get("valid_answers") or 0) + sum(
        int(excluded.get(key) or 0)
        for key in ("failed", "manual_review", "no_answer_surface", "pending_or_running")
    )


def _engine_rows(snapshot: StatSnapshot) -> list[dict]:
    return list((snapshot.metrics or {}).get("by_engine") or [])


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

    b_versions = {str(item.get("id")): item for item in b_scope.get("question_versions") or []}
    c_versions = {str(item.get("id")): item for item in c_scope.get("question_versions") or []}
    common_versions = set(b_versions) & set(c_versions)
    b_modes = sorted(b_scope.get("sampling_modes") or [])
    c_modes = sorted(c_scope.get("sampling_modes") or [])
    b_api_entries = {
        item["id"]: item for item in b_scope.get("engine_entries") or []
        if str(item.get("name", "")).find("网页版") < 0
    }
    c_api_entries = {
        item["id"]: item for item in c_scope.get("engine_entries") or []
        if str(item.get("name", "")).find("网页版") < 0
    }
    common_entries = set(b_api_entries) & set(c_api_entries)

    b_samples = _sample_count(b_over)
    c_samples = _sample_count(c_over)
    b_web_samples = int(baseline_samples.get("web_user", 0))
    c_web_samples = int(candidate_samples.get("web_user", 0))
    b_api_samples = int(baseline_samples.get("api", 0))
    c_api_samples = int(candidate_samples.get("api", 0))

    lines: list[str] = []
    add = lines.append
    add(f"# {project.name} P32 同题同引擎同模式复测报告")
    add("")
    add("> 对比对象：seq3（基线，历史混合·含 API 追加） vs seq4（复测，API 实采）。")
    add("> 指标全部来自两轮已冻结的 `stat_snapshots`；样本/任务覆盖另查任务与样本表，只用于说明边界。")
    add("")
    add("## 0. 快照与轮次")
    add("")
    add("| 项 | seq3（基线） | seq4（复测） |")
    add("|---|---|---|")
    add(f"| 轮次名称 | {_cell(baseline_round.name)} | {_cell(candidate_round.name)} |")
    add(f"| 轮次状态 | `{_enum_value(baseline_round.status)}` | `{_enum_value(candidate_round.status)}` |")
    add(f"| 快照 ID | `{baseline.id}` | `{candidate.id}` |")
    add(f"| 快照 hash | `{baseline.snapshot_hash}` | `{candidate.snapshot_hash}` |")
    add(f"| 冻结时间 | {_fmt_time(baseline.captured_at)} | {_fmt_time(candidate.captured_at)} |")
    add(f"| 规则版本 | `{baseline.rule_version}` | `{candidate.rule_version}` |")
    add("")

    add("## 1. 可比性")
    add("")
    add("| 维度 | seq3 | seq4 | 是否可比 |")
    add("|---|---|---|---|")
    add(f"| 题目版本 | {len(b_versions)} 个，均为 v2 | {len(c_versions)} 个，均为 v2 | 共同版本 {len(common_versions)} 个，{'是' if len(common_versions) == len(b_versions) == len(c_versions) else '否'} |")
    add(f"| API 入口 | {len(b_api_entries)} 个 | {len(c_api_entries)} 个 | 共同入口 {len(common_entries)} 个，{'是' if len(common_entries) == len(b_api_entries) == len(c_api_entries) else '否'} |")
    add(f"| 采样模式 | {', '.join(b_modes) or '—'} | {', '.join(c_modes) or '—'} | {'是' if b_modes == c_modes else '否'} |")
    add(f"| API 样本 | {b_api_samples} | {c_api_samples} | 同引擎同模式；seq4 多 1 条 DeepSeek 样本 |")
    add(f"| web_user 样本 | {b_web_samples} | {c_web_samples} | 两轮均未执行用户端，不能形成用户端对比 |")
    add("")
    add("结论：**API 层**满足“同题（6 个 v2）同引擎（4 个 API 入口）同模式（search_on）”；**用户端 web_user 两轮均为 0 样本**，因此本报告只对 API 层负责，不外推到网页端/人工端。")
    add("")

    add("## 2. 核心指标对比")
    add("")
    add("| 指标 | seq3（基线） | seq4（复测） | 差值 |")
    add("|---|---:|---:|---:|")
    add(f"| 总样本（有效+排除） | {b_samples} | {c_samples} | {c_samples - b_samples:+d} |")
    add(f"| 有效回答 | {int(b_over.get('valid_answers') or 0)} | {int(c_over.get('valid_answers') or 0)} | {int(c_over.get('valid_answers') or 0) - int(b_over.get('valid_answers') or 0):+d} |")
    add(f"| 失败样本 | {int((b_over.get('excluded') or {}).get('failed') or 0)} | {int((c_over.get('excluded') or {}).get('failed') or 0)} | {int((c_over.get('excluded') or {}).get('failed') or 0) - int((b_over.get('excluded') or {}).get('failed') or 0):+d} |")
    add(f"| 品牌提及回答 | {int(b_over.get('brand_mentioned_answers') or 0)} | {int(c_over.get('brand_mentioned_answers') or 0)} | {int(c_over.get('brand_mentioned_answers') or 0) - int(b_over.get('brand_mentioned_answers') or 0):+d} |")
    add(f"| 品牌提及率 | {_pct(b_over.get('brand_mention_rate'))} | {_pct(c_over.get('brand_mention_rate'))} | {_pp((c_over.get('brand_mention_rate') or 0) - (b_over.get('brand_mention_rate') or 0))} |")
    add(f"| 品牌识别回答 | {int(b_over.get('brand_identified_answers') or 0)} | {int(c_over.get('brand_identified_answers') or 0)} | {int(c_over.get('brand_identified_answers') or 0) - int(b_over.get('brand_identified_answers') or 0):+d} |")
    add(f"| 品牌识别率 | {_pct(b_over.get('brand_identified_rate'))} | {_pct(c_over.get('brand_identified_rate'))} | {_pp((c_over.get('brand_identified_rate') or 0) - (b_over.get('brand_identified_rate') or 0))} |")
    add(f"| 引用回答 | {int(b_over.get('citation_answers') or 0)} | {int(c_over.get('citation_answers') or 0)} | {int(c_over.get('citation_answers') or 0) - int(b_over.get('citation_answers') or 0):+d} |")
    add(f"| 引用率 | {_pct(b_over.get('citation_rate'))} | {_pct(c_over.get('citation_rate'))} | {_pp((c_over.get('citation_rate') or 0) - (b_over.get('citation_rate') or 0))} |")
    add(f"| 渠道数 | {int(b_over.get('channel_count') or 0)} | {int(c_over.get('channel_count') or 0)} | {int(c_over.get('channel_count') or 0) - int(b_over.get('channel_count') or 0):+d} |")
    add("")
    add("解释：品牌提及率上升 **7.07pp**，来自有效回答增加 4 条、提及回答增加 2 条；绝对样本仍很小，不能据此断言内容优化生效。引用回答两轮均为 0，与“没有引用 URL 命中发布回执”一致。")
    add("")

    add("## 3. 分引擎对比")
    add("")
    add("| 引擎 | seq3 有效/提及 | seq3 提及率 | seq4 有效/提及 | seq4 提及率 | 有效差值 | 提及率差值 |")
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
    add("分引擎仍是小样本：单引擎有效回答 3–7 条，任一单条样本都会造成 14–33pp 的跳动；只用于定位下一步复测重点，不作为效果排名。")
    add("")

    add("## 4. 结论与边界")
    add("")
    add("- **成立**：两轮题目版本、API 入口、采样模式一致，且两轮都快照冻结；API 层可形成可审计的同题复测报告。")
    add("- **不成立/未覆盖**：web_user 两轮均 0 样本；没有 search_off 对照；seq3 名称含“历史混合·含API追加”，seq4 为 API 实采，样本构成并非完全同质。")
    add("- **不能推断**：品牌提及率 +7.07pp 是内容、时间还是样本波动导致的；本报告只记录差值，不做因果结论。")
    add("- **下一步**：若要把 P32 从“API 层可比”提升到“用户端也可比”，必须补 web_user 的真实人工采样；不能拿 API 结果替代。")
    add("")

    add("## 5. 复验入口")
    add("")
    add("```powershell")
    add("docker exec geo-postgres psql -U geo -d geo -P pager=off \\")
    add(f"  -c \"select id, round_id, captured_at, snapshot_hash from stat_snapshots where round_id in ('{baseline.round_id}','{candidate.round_id}');\"")
    add("```")
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", default=str(DEFAULT_PROJECT_ID))
    parser.add_argument("--baseline-round", default=str(DEFAULT_BASELINE_ROUND))
    parser.add_argument("--candidate-round", default=str(DEFAULT_CANDIDATE_ROUND))
    parser.add_argument("--output", required=True)
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
            raise SystemExit("缺少轮次冻结快照；请先调用 create_round_snapshot")
        baseline_tasks, baseline_samples = _task_sample_counts(db, project_id, baseline_round_id)
        candidate_tasks, candidate_samples = _task_sample_counts(db, project_id, candidate_round_id)
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
        )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    print(f"written: {output} ({len(markdown)} bytes)")


if __name__ == "__main__":
    main()
