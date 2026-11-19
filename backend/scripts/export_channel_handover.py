"""生成渠道台账交接记录（P34）。

区分两层：
- published：引用 URL 命中发布回执，写 `channel_id`，计入渠道效果 `channel_count`；
- observed：人工确认引用命中渠道主域名/别名，只做信源层观测，不写 `channel_id`。
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Channel,
    ChannelAlias,
    MonitoringCitation,
    Project,
    PublishReceipt,
)
from app.models.enums import CitationReviewStatus  # noqa: E402,F401

DEFAULT_PROJECT_ID = uuid.UUID("154640d4-6356-4a1c-8bde-2d511cfb06cd")
CATEGORY_LABELS = {
    "own_site": "自有站点", "content_platform": "内容平台", "video": "视频平台",
    "community": "社区", "encyclopedia": "百科", "local_media": "地方媒体",
    "industry_media": "行业媒体", "institution": "机构",
}
STATUS_LABELS = {
    "candidate": "候选", "observed": "已观测", "published": "已发布", "review_pending": "待审核",
}


def _cell(value: object) -> str:
    return str(value or "—").replace("|", "\\|").replace("\n", " ")


def _domain_key(value: str | None) -> str:
    key = (value or "").strip().casefold().strip(".")
    return key[4:] if key.startswith("www.") else key


def _match_domain(domain: str | None, index: dict[str, uuid.UUID]) -> uuid.UUID | None:
    key = _domain_key(domain)
    if not key or "." not in key:
        return index.get(key) if key else None
    candidate = key
    while "." in candidate:
        if candidate in index:
            return index[candidate]
        candidate = candidate.split(".", 1)[1]
    return None


def build_markdown(
    *,
    project: Project,
    channels: list[Channel],
    aliases: dict[uuid.UUID, list[str]],
    citation_stats: dict[str, dict],
    published_by_channel: dict[uuid.UUID, int],
    total_citations: int,
    confirmed_citations: int,
    unconfirmed_citations: int,
    published_citations: int,
    receipts: int,
    kr_citations: int,
) -> str:
    index: dict[str, uuid.UUID] = {}
    for channel in channels:
        domains = [channel.primary_domain, *aliases.get(channel.id, [])]
        for domain in domains:
            key = _domain_key(domain)
            if key:
                index.setdefault(key, channel.id)

    observed_by_channel: dict[uuid.UUID, dict] = {}
    observed_total = 0
    max_domain = None
    for domain, stats in citation_stats.items():
        channel_id = _match_domain(domain, index)
        if channel_id is None:
            continue
        observed_total += stats["citations"]
        bucket = observed_by_channel.setdefault(
            channel_id, {"citations": 0, "samples": 0, "pages": 0, "domains": []}
        )
        bucket["citations"] += stats["citations"]
        bucket["samples"] += stats["samples"]
        bucket["pages"] += stats["pages"]
        bucket["domains"].append(domain)
        if max_domain is None or stats["citations"] > max_domain[1]["citations"]:
            max_domain = (domain, stats)

    category_counts = Counter(str(category) for category in (channel.category for channel in channels))
    status_counts = Counter(str(status) for status in (channel.status for channel in channels))
    owner_count = sum(1 for channel in channels if channel.owner_name)

    lines: list[str] = []
    add = lines.append
    add("# 渠道台账与渠道明细交接记录（P34）")
    add("")
    add("- 日期：2026-11-19")
    add(f"- 项目：{project.name}（`{project.code}`，`project_id={project.id}`）")
    add("- 验收项：P34「第4周开发：基线对比、引擎与渠道明细、导出和交接」")
    add("- 口径：渠道效果只认发布回执 URL；域名命中只做信源观测，不写 `channel_id`、不计 `channel_count`。")
    add("")
    add("## 1. 结论")
    add("")
    add(f"- 渠道台账 **{len(channels)}** 条，字段包含 code/name/category/status/primary_domain/owner/publish_url/login_url/notes/aliases，可逐条打开明细。")
    add(f"- 发布回执归因引用 **{published_citations}** 条；`channel_count=0` 是真实数据事实，不是接口不可用。")
    add(f"- 引用总数 **{total_citations}** 条，其中人工确认 **{confirmed_citations}** 条、未确认 **{unconfirmed_citations}** 条；确认引用里能按域名观测到渠道的 **{observed_total}** 条，覆盖 **{len(observed_by_channel)}** 个渠道。")
    add(f"- 36氪域名引用 **{kr_citations}** 条；当前没有 36氪引用可归因到 36氪渠道，不能用假 URL 回填。")
    add(f"- 发布回执 **{receipts}** 条，均为流程演练/测试地址；不能作为真实渠道发布证据。")
    add("- 基线对比、分引擎/分题/信源、统计 CSV、渠道 CSV 导出均已具备；本次补的是渠道明细的“域名观测”层与正式交接记录。")
    add("")

    add("## 2. 台账规模")
    add("")
    add("| 维度 | 数量 |")
    add("|---|---:|")
    add(f"| 渠道总数 | {len(channels)} |")
    add(f"| 有负责人 | {owner_count} |")
    add("")
    add("分类分布：")
    add("")
    add("| 分类 | 数量 |")
    add("|---|---:|")
    for code, count in sorted(category_counts.items()):
        add(f"| {CATEGORY_LABELS.get(code, code)} | {count} |")
    add("")
    add("状态分布：")
    add("")
    add("| 状态 | 数量 |")
    add("|---|---:|")
    for code, count in sorted(status_counts.items()):
        add(f"| {STATUS_LABELS.get(code, code)} | {count} |")
    add("")

    add("## 3. 渠道明细可用性")
    add("")
    add("打开任一渠道后，详情接口/弹窗分两层展示：")
    add("")
    add("| 层 | 字段 | 含义 |")
    add("|---|---|---|")
    add("| 发布回执归因 | `citation_count` / `sample_count` / `page_count` / `page_urls` / `citations` | 只有引用 URL 命中我们真实发布回执才计入；代表渠道效果，计入 `channel_count` |")
    add("| 域名观测 | `observed_domain_count` / `observed_citation_count` / `observed_sample_count` / `observed_page_count` / `observed_page_urls` / `observed_citations` | 人工确认引用命中渠道主域名/别名；只代表 AI 在哪个平台取证，不计渠道效果 |")
    add("")
    add("为什么要分两层：`citation_attribution.py` 明确只按发布回执 URL 归因；域名匹配会把平台上任何一篇文章都算成我们的渠道稿，导致渠道效果虚高。本次没有改这个口径，只把域名观测作为只读的第二层明细。")
    add("")
    add("## 4. 域名观测 Top")
    add("")
    if max_domain:
        add("| 域名 | 人工确认引用 | 样本 | 页面 |")
        add("|---|---:|---:|---:|")
        top = sorted(citation_stats.items(), key=lambda item: item[1]["citations"], reverse=True)[:15]
        for domain, stats in top:
            add(f"| {_cell(domain)} | {stats['citations']} | {stats['samples']} | {stats['pages']} |")
    else:
        add("暂无可观测域名。")
    add("")
    add("这些域名只用于回答“AI 从哪些平台取证、下一轮该在哪发”，不能直接写成“渠道稿带来 N 条引用”。")
    add("")

    add("## 5. 台账全量清单")
    add("")
    add("| # | 代码 | 名称 | 分类 | 状态 | 主域名 | 负责人 | 发布回执归因 | 域名观测引用 |")
    add("|---:|---|---|---|---|---|---|---:|---:|")
    for index_no, channel in enumerate(sorted(channels, key=lambda item: item.code), start=1):
        observed = observed_by_channel.get(channel.id, {})
        add(
            f"| {index_no} | `{channel.code}` | {_cell(channel.name)} | "
            f"{CATEGORY_LABELS.get(str(channel.category), str(channel.category))} | "
            f"{STATUS_LABELS.get(str(channel.status), str(channel.status))} | "
            f"{_cell(channel.primary_domain)} | {_cell(channel.owner_name)} | "
            f"{published_by_channel.get(channel.id, 0)} | {observed.get('citations', 0)} |"
        )
    add("")
    add("负责人联系方式、发布后台、登录页、备注、别名等字段在渠道详情弹窗中逐条展示，不在交接表里展开。")
    add("")

    add("## 6. 验收路径")
    add("")
    add("1. 打开渠道台账页，目录规模应为 43 条；分页 1/3。")
    add("2. 打开任一渠道（例如 `baijiahao`），应看到“发布回执归因：引用 0 条”，以及“域名观测（人工确认引用，仅信源层）”的引用/样本/页面数量与 URL。")
    add("3. 打开 `36kr`，应看到发布回执归因 0、域名观测 0；这是数据事实，不是 404/500。")
    add("4. 统计页选择 seq4、非基线轮次时，应展示较基线差值；选“全部轮次”不显示差值。")
    add("5. 点击“导出 CSV”应下载统计 CSV；渠道页“导出 CSV”应下载渠道台账/筛选覆盖表。")
    add("")
    add("复验命令：")
    add("")
    add("```powershell")
    add("docker exec geo-postgres psql -U geo -d geo -P pager=off \\")
    add("  -c \"select count(*) from channels;\" \\")
    add("  -c \"select count(*) from monitoring_citations where channel_id is not null;\" \\")
    add("  -c \"select count(*) from monitoring_citations where review_status='manual_confirmed';\" \\")
    add("  -c \"select count(*) from monitoring_citations where domain ilike '%36kr%';\"")
    add("```")
    add("")

    add("## 7. 交接边界")
    add("")
    add("- 43 条渠道台账可用；不是“空表”。")
    add("- 渠道效果为 0：625 条引用 `channel_id` 全空；只有 2 条测试回执，且没有引用 URL 命中。")
    add("- 真实发布后，回执落库会自动触发同一 URL 的历史引用回刷；回刷前不要手工把域名引用挂到渠道，否则会污染渠道效果。")
    add("- 交接给运营：维护负责人/主域名/别名/发布后台；交接给开发：真实回执后跑 `backfill_project_citations` 并复核 `channel_count`。")
    add("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", default=str(DEFAULT_PROJECT_ID))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    project_id = uuid.UUID(args.project_id)
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        if project is None:
            raise SystemExit(f"项目不存在: {project_id}")
        channels = db.scalars(
            select(Channel).where(Channel.project_id == project_id).order_by(Channel.code)
        ).all()
        alias_rows = db.execute(
            select(ChannelAlias.channel_id, ChannelAlias.domain).where(
                ChannelAlias.project_id == project_id
            )
        ).all()
        aliases: dict[uuid.UUID, list[str]] = {}
        for channel_id, domain in alias_rows:
            aliases.setdefault(channel_id, []).append(domain)
        total_citations = int(db.scalar(
            select(func.count()).select_from(MonitoringCitation).where(
                MonitoringCitation.project_id == project_id
            )
        ) or 0)
        confirmed_citations = int(db.scalar(
            select(func.count()).select_from(MonitoringCitation).where(
                MonitoringCitation.project_id == project_id,
                MonitoringCitation.review_status == "manual_confirmed",
            )
        ) or 0)
        unconfirmed_citations = total_citations - confirmed_citations
        published_citations = int(db.scalar(
            select(func.count()).select_from(MonitoringCitation).where(
                MonitoringCitation.project_id == project_id,
                MonitoringCitation.channel_id.is_not(None),
            )
        ) or 0)
        published_rows = db.execute(
            select(MonitoringCitation.channel_id, func.count())
            .where(
                MonitoringCitation.project_id == project_id,
                MonitoringCitation.channel_id.is_not(None),
            )
            .group_by(MonitoringCitation.channel_id)
        ).all()
        published_by_channel = {channel_id: int(count) for channel_id, count in published_rows}
        citation_stats: dict[str, dict] = {}
        stats_rows = db.execute(
            select(
                MonitoringCitation.domain,
                func.count(),
                func.count(func.distinct(MonitoringCitation.sample_id)),
                func.count(func.distinct(MonitoringCitation.normalized_url)),
            )
            .where(
                MonitoringCitation.project_id == project_id,
                MonitoringCitation.review_status == "manual_confirmed",
                MonitoringCitation.domain.is_not(None),
            )
            .group_by(MonitoringCitation.domain)
        ).all()
        for domain, citations, samples, pages in stats_rows:
            citation_stats[domain] = {
                "citations": int(citations),
                "samples": int(samples),
                "pages": int(pages),
            }
        receipts = int(db.scalar(
            select(func.count()).select_from(PublishReceipt).where(
                PublishReceipt.project_id == project_id
            )
        ) or 0)
        kr_citations = int(db.scalar(
            select(func.count()).select_from(MonitoringCitation).where(
                MonitoringCitation.project_id == project_id,
                MonitoringCitation.domain.ilike("%36kr%"),
            )
        ) or 0)
        markdown = build_markdown(
            project=project,
            channels=list(channels),
            aliases=aliases,
            citation_stats=citation_stats,
            published_by_channel=published_by_channel,
            total_citations=total_citations,
            confirmed_citations=confirmed_citations,
            unconfirmed_citations=unconfirmed_citations,
            published_citations=published_citations,
            receipts=receipts,
            kr_citations=kr_citations,
        )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    print(f"written: {output} ({len(markdown)} bytes)")


if __name__ == "__main__":
    main()
