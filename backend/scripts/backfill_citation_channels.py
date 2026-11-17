"""回刷引用 → 渠道归属（`monitoring_citations.channel_id`）。

口径：只认**发布回执里的真实 URL**（`publish_receipts.published_url` → 回执所属
`publish_tasks.channel_id`）。域名级匹配会把整站都算成"我们渠道被引"，已废弃。

采集侧新写入时已按同一口径补齐；本脚本处理历史数据，只动 `channel_id IS NULL`
的行，幂等。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\backfill_citation_channels.py --dry-run
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\backfill_citation_channels.py
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\backfill_citation_channels.py --project-code gz-base
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Project
from app.services.citation_attribution import backfill_project_citations


def main() -> int:
    parser = argparse.ArgumentParser(description="按发布回执回刷引用的渠道归属")
    parser.add_argument("--project-code", help="只处理该项目；不传则处理全部项目")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    args = parser.parse_args()

    with SessionLocal() as db:
        query = select(Project)
        if args.project_code:
            query = query.where(Project.code == args.project_code)
        projects = db.scalars(query.order_by(Project.code)).all()
        if not projects:
            print(f"未找到项目：{args.project_code}")
            return 1

        total_candidates = total_matched = 0
        for project in projects:
            result = backfill_project_citations(db, project.id, dry_run=args.dry_run)
            total_candidates += result["candidates"]
            total_matched += result["matched"]
            print(
                f"{project.code}: 待归类引用 {result['candidates']} 条 → 命中发布回执 "
                f"{result['matched']} 条（回执 {result['published_urls']} 条）"
            )
        mode = "预演（未写库）" if args.dry_run else "已写库"
        print(f"合计：{total_candidates} 条待归类 → 命中 {total_matched} 条；{mode}")
        if total_candidates and not total_matched:
            print(
                "提示：命中需要『同一 URL』——引用里必须出现我们发布回执的地址。"
                "先跑发布流程写回执（POST /publish-tasks / /publish-receipts），或确认 URL 是否带跟踪参数。"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
