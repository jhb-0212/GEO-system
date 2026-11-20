"""首月报告 Markdown 渲染：只消费真实月报数据与选题计划。"""

from __future__ import annotations

from datetime import datetime


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.2f}%"


def render_monthly_report(
    *,
    month: str,
    period_start: datetime | None,
    period_end: datetime | None,
    tasks: dict,
    answers: dict,
    leads: dict | None,
    published_receipts: int,
    evidence: dict,
    plans: list[dict],
    generated_at: datetime,
) -> str:
    lines = [
        f"# 广州基地 GEO 首月报告（{month}）",
        "",
        f"> 生成时间：{generated_at.isoformat()}",
        f"> 数据范围：{period_start} 至 {period_end}",
        "> 口径：监测样本按有效回答与失败单列；引用率只统计品牌相关且人工确认的引用；线索为 0 时保留空值，不推算。",
        "",
        "## 1. 监测完成情况",
        "",
        f"- 任务总数：{tasks.get('total', 0)}；完成 {tasks.get('done', 0)}；失败 {tasks.get('failed', 0)}；"
        f"待执行 {tasks.get('pending', 0)}；完成率 {_pct(tasks.get('completion_rate'))}。",
        f"- 有效回答：{answers.get('valid_answers', 0)}；样本总数 {answers.get('total_samples', 0)}；"
        f"失败率 {_pct(answers.get('failure_rate'))}。",
        f"- 品牌提及回答：{answers.get('brand_mentioned_answers', 0)}；"
        f"品牌提及率 {_pct(answers.get('brand_mention_rate'))}。",
        f"- 引用回答：{answers.get('citation_answers', 0)}；引用率 {_pct(answers.get('citation_rate'))}。",
        f"- 24 小时新鲜样本率：{_pct(answers.get('fresh_24h_rate'))}；"
        f"题目覆盖 {_pct(answers.get('prompt_coverage'))}。",
        "",
        "## 2. 证据与可回看",
        "",
        f"- 样本证据覆盖：{evidence.get('samples_with_evidence', 0)}/{evidence.get('total_samples', 0)}，"
        f"覆盖率 {_pct(evidence.get('coverage_rate'))}；缺失 {evidence.get('samples_missing_evidence', 0)} 条。",
        "",
        "## 3. 内容与发布",
        "",
        f"- 发布回执：{published_receipts} 条；真实站外发布按发布任务回执单独核对，测试 URL 不计入真实发布。",
        "",
        "## 4. 线索与转化",
        "",
    ]
    if leads is None:
        lines.append("- 当前账号没有线索查看权限，本节不输出线索数据。")
    else:
        lines.extend([
            f"- 线索总数：{leads.get('total', 0)}；有效 {leads.get('valid', 0)}；已联系 {leads.get('contacted', 0)}；"
            f"已报名 {leads.get('enrolled', 0)}。",
            f"- 可追踪访问：{leads.get('ai_attribution', {}).get('trackable_visits', 0)}；"
            f"监测引用 {leads.get('ai_attribution', {}).get('monitored_citations', 0)} 条 / "
            f"{leads.get('ai_attribution', {}).get('monitored_citation_urls', 0)} 个 URL。",
        ])
    lines.extend([
        "",
        "## 5. 下月选题",
        "",
        "| 类型 | 状态 | 选题 | 负责人 | 渠道 | 排期 |",
        "|---|---|---|---|---|---|",
    ])
    for plan in plans:
        lines.append(
            "| {plan_type} | {status} | {title} | {owner} | {channel} | {scheduled} |".format(
                plan_type=plan.get("plan_type") or "—",
                status=plan.get("status") or "—",
                title=plan.get("title") or "—",
                owner=plan.get("owner") or "—",
                channel=plan.get("channel") or "—",
                scheduled=plan.get("scheduled_at") or "—",
            )
        )
    if not plans:
        lines.append("| — | — | 暂未登记下月选题 | — | — | — |")
    lines.extend(
        [
            "",
            "## 6. 结论与待补",
            "",
            "- 监测主干、24 格基线、证据覆盖与月报口径已形成；真实站外发布、线索回填、人工复核仍是首月外部动作缺口。",
            "- 本报告不把测试回执、自动评论或未确认引用计入真实业务结果；下月选题以 `content_plans` 登记为准。",
            "",
        ]
    )
    return "\n".join(lines)
