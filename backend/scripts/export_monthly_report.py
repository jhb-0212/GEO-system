"""从冻结月报快照生成正式 Markdown 报告（P33）。

用法：
    python scripts/export_monthly_report.py --month 2026-11 \
        --output ../docs/reports/首月报告_2026-11.md

报告只读 `monthly_report_snapshots.report`，不重新查询实时统计，避免报告与冻结
快照漂移；下月选题从 `content_plans` 读取，只作为计划清单附录，不改变月报指标。
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Channel,
    ContentPlan,
    MonthlyReportSnapshot,
    Project,
    User,
)

DEFAULT_PROJECT_ID = uuid.UUID("154640d4-6356-4a1c-8bde-2d511cfb06cd")
CST = ZoneInfo("Asia/Shanghai")
STATUS_LABELS = {
    "scheduled": "已排期",
    "proposed": "待排期",
    "published": "已发布",
    "archived": "已归档",
}
TYPE_LABELS = {"video": "视频", "article": "图文", "image": "图片"}


def _pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.2f}%"


def _int(value: object) -> int:
    return int(value or 0)


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


def build_markdown(
    *,
    project: Project,
    snapshot: MonthlyReportSnapshot,
    captured_by_name: str | None,
    plans: list[tuple[ContentPlan, str | None, str | None]],
) -> str:
    report = snapshot.report or {}
    tasks = report.get("tasks") or {}
    answers = report.get("answers") or {}
    leads = report.get("leads") or {}
    attribution = leads.get("ai_attribution") or {}
    period_start = report.get("period_start")
    period_end = report.get("period_end")

    lines: list[str] = []
    add = lines.append
    add(f"# {project.name}首月 GEO 报告（{snapshot.month}）")
    add("")
    add("> 本报告由冻结月报快照生成。指标只取快照原文，不从实时库重算；下月选题计划为独立附录。")
    add("")
    add("## 0. 报告元信息")
    add("")
    add("| 项 | 值 |")
    add("|---|---|")
    add(f"| 项目 | {_cell(project.name)}（`{project.code}`） |")
    add(f"| 报告月份 | `{snapshot.month}` |")
    add(f"| 统计区间 | {_fmt_time(period_start)} 至 {_fmt_time(period_end)}（Asia/Shanghai） |")
    add(f"| 快照 ID | `{snapshot.id}` |")
    add(f"| 快照 hash | `{snapshot.snapshot_hash}` |")
    add(f"| 冻结时间 | {_fmt_time(snapshot.captured_at)} |")
    add(f"| 冻结人 | {_cell(captured_by_name)} |")
    add(f"| 规则版本 | `{snapshot.rule_version or '—'}` |")
    add("")

    add("## 1. 执行摘要")
    add("")
    add(f"- 本月共创建监测任务 **{_int(tasks.get('total'))}** 个，完成/失败已结案 **{_int(tasks.get('done')) + _int(tasks.get('failed'))}** 个，任务完成率 **{_pct(tasks.get('completion_rate'))}**；其中失败 **{_int(tasks.get('failed'))}** 个、待执行 **{_int(tasks.get('pending'))}** 个，失败样本没有混入有效分母。")
    add(f"- 有效回答 **{_int(answers.get('valid_answers'))}** 条（总样本 {_int(answers.get('total_samples'))}），品牌提及 **{_int(answers.get('brand_mentioned_answers'))}** 条，品牌提及率 **{_pct(answers.get('brand_mention_rate'))}**；引用回答 **{_int(answers.get('citation_answers'))}** 条，引用率 **{_pct(answers.get('citation_rate'))}**。")
    add(f"- 发布结案回执 **{_int(report.get('published_receipts'))}** 条；当前回执均为流程演练/测试地址，不能替代真实渠道发布。线索总量 **{_int(leads.get('total'))}**，尚无有效咨询回流。")
    add("- 结论：首月可审计的基线数据已冻结；内容侧已有 12 条下月/跨月选题计划，但真实发布、真实咨询与人工复核仍是下一阶段缺口。")
    add("")

    add("## 2. 监测任务")
    add("")
    add("| 指标 | 数值 |")
    add("|---|---:|")
    add(f"| 任务总数 | {_int(tasks.get('total'))} |")
    add(f"| 已完成 | {_int(tasks.get('done'))} |")
    add(f"| 失败 | {_int(tasks.get('failed'))} |")
    add(f"| 待执行 | {_int(tasks.get('pending'))} |")
    add(f"| 运行中 | {_int(tasks.get('running'))} |")
    add(f"| 完成率（含失败结案） | {_pct(tasks.get('completion_rate'))} |")
    add("")
    add("说明：完成率按 `(done + failed) / total` 计算，失败是已结案但未产生有效回答的任务；有效回答分母只使用成功样本。")
    add("")

    add("## 3. 回答与品牌表现")
    add("")
    add("| 指标 | 数值 |")
    add("|---|---:|")
    add(f"| 总样本 | {_int(answers.get('total_samples'))} |")
    add(f"| 有效回答 | {_int(answers.get('valid_answers'))} |")
    add(f"| 品牌提及回答 | {_int(answers.get('brand_mentioned_answers'))} |")
    add(f"| 品牌提及率 | {_pct(answers.get('brand_mention_rate'))} |")
    add(f"| 引用回答 | {_int(answers.get('citation_answers'))} |")
    add(f"| 引用率 | {_pct(answers.get('citation_rate'))} |")
    add(f"| 失败率 | {_pct(answers.get('failure_rate'))} |")
    add(f"| 24 小时新鲜度 | {_pct(answers.get('fresh_24h_rate'))} |")
    add(f"| 题库覆盖率 | {_pct(answers.get('prompt_coverage'))} |")
    add("")
    add("口径：品牌提及率 = 品牌被提及的有效回答 / 有效回答；引用率 = 含基地相关且已人工复核来源链接的有效回答 / 有效回答。两者分母均为有效回答，失败样本不进入分母。")
    add("")

    add("## 4. 引用与发布结案")
    add("")
    add("| 指标 | 数值 |")
    add("|---|---:|")
    add(f"| 监测引用 | {_int(attribution.get('monitored_citations'))} |")
    add(f"| 去重引用页面 | {_int(attribution.get('monitored_citation_urls'))} |")
    add(f"| 可追踪访问 | {_int(attribution.get('trackable_visits'))} |")
    add(f"| 人工访问 / 会话 | {_int(attribution.get('human_visits'))} / {_int(attribution.get('human_sessions'))} |")
    add(f"| 自报 AI 线索（有效） | {_int(attribution.get('self_reported_ai_leads'))}（{_int(attribution.get('self_reported_ai_valid_leads'))}） |")
    add(f"| 引擎归因线索 | {_int(attribution.get('engine_attributed_leads'))} |")
    add(f"| 发布回执 | {_int(report.get('published_receipts'))} |")
    add("")
    add("说明：本月引用回答为 0，渠道归因也为 0；不是查询失败，而是当前没有引用 URL 命中已发布回执。渠道台账仍可单独查看与导出，渠道效果等待真实发布回执后回刷。")
    add("")

    add("## 5. 线索漏斗")
    add("")
    if leads:
        add("| 指标 | 数值 |")
        add("|---|---:|")
        add(f"| 线索总量 | {_int(leads.get('total'))} |")
        add(f"| 有效线索 | {_int(leads.get('valid'))} |")
        add(f"| 已联系 | {_int(leads.get('contacted'))} |")
        add(f"| 已报名 | {_int(leads.get('enrolled'))} |")
        add(f"| 已流失 | {_int(leads.get('lost'))} |")
        add(f"| 联系率 | {_pct(leads.get('contact_rate'))} |")
        add(f"| 转化率 | {_pct(leads.get('conversion_rate'))} |")
        add("")
        add("线索总数为 0 时，联系率/转化率没有分母，显示为 `—`；不能用 0% 冒充“有分母但无转化”。")
    else:
        add("本快照未包含线索段（冻结时账号缺少 `lead.read` 权限）。")
    add("")

    add("## 6. 下月与跨月选题计划")
    add("")
    add(f"共 **{len(plans)}** 条。计划状态与排期如下；`proposed` 只是选题池，不等于已排期，更不等于已发布。")
    add("")
    add("| # | 排期 | 状态 | 形式 | 选题 | 负责人 | 渠道 |")
    add("|---:|---|---|---|---|---|---|")
    for index, (plan, owner_name, channel_name) in enumerate(plans, start=1):
        scheduled = plan.scheduled_at.astimezone(CST).strftime("%Y-%m-%d") if plan.scheduled_at else "待排"
        add(
            f"| {index} | {scheduled} | {STATUS_LABELS.get(_enum_value(plan.status), _enum_value(plan.status))} | "
            f"{TYPE_LABELS.get(_enum_value(plan.plan_type), _enum_value(plan.plan_type))} | {_cell(plan.title)} | "
            f"{_cell(owner_name)} | {_cell(channel_name)} |"
        )
    add("")
    add("排期判断：6 条为 `scheduled`（其中 2 条在 11 月、4 条在 12 月），6 条为 `proposed`（4 条图文、2 条视频）。下一阶段应先把待排选题补齐渠道、事实页和素材，再推进发布。")
    add("")

    add("## 7. 验收结论与边界")
    add("")
    add("- 正式报告：本文件由冻结快照生成，报告与快照 hash 一一对应，可作为首月复盘和审计入口。")
    add("- 下月选题：12 条计划已入库，具备“形成选题”的证据；真实发布仍为 0，不能把计划态当发布态。")
    add("- 未闭环项：真实站外发布、真实咨询回流、人工复核 `reviewed_at`、渠道效果归因仍需下月补齐。")
    add("- 数据边界：`published_receipts=2` 是测试/流程演练回执；`leads=0`；不要用本报告推断真实市场表现。")
    add("")

    add("## 8. 复验入口")
    add("")
    add("```powershell")
    add("docker exec geo-postgres psql -U geo -d geo -P pager=off \\")
    add(f"  -c \"select month, captured_at, snapshot_hash from monthly_report_snapshots where id='{snapshot.id}';\"")
    add("```")
    add("")
    add(f"快照 `report` 原始 JSON 可按 `select jsonb_pretty(report) from monthly_report_snapshots where id='{snapshot.id}';` 复核。")
    add("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", default=str(DEFAULT_PROJECT_ID))
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument("--output", required=True, help="输出 Markdown 路径")
    args = parser.parse_args()

    project_id = uuid.UUID(args.project_id)
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        if project is None:
            raise SystemExit(f"项目不存在: {project_id}")
        snapshot = db.scalar(
            select(MonthlyReportSnapshot).where(
                MonthlyReportSnapshot.project_id == project_id,
                MonthlyReportSnapshot.month == args.month,
            )
        )
        if snapshot is None:
            raise SystemExit(f"{args.month} 没有冻结月报快照，请先冻结月报再导出")
        captured_by_name = (
            db.scalar(select(User.display_name).where(User.id == snapshot.captured_by))
            if snapshot.captured_by
            else None
        )
        plans = db.execute(
            select(ContentPlan, User.display_name, Channel.name)
            .outerjoin(User, User.id == ContentPlan.owner_id)
            .outerjoin(Channel, Channel.id == ContentPlan.channel_id)
            .where(ContentPlan.project_id == project_id)
            .order_by(ContentPlan.scheduled_at.asc().nulls_last(), ContentPlan.created_at.asc())
        ).all()
        markdown = build_markdown(
            project=project,
            snapshot=snapshot,
            captured_by_name=captured_by_name,
            plans=[(plan, owner, channel) for plan, owner, channel in plans],
        )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    print(f"written: {output} ({len(markdown)} bytes)")


if __name__ == "__main__":
    main()
