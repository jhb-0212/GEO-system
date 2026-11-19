"""补建历史 AI 引用的未知域名审核队列。

采集侧只在新样本写入时建 `citation_source_reviews`；本脚本扫描历史引用域名，
跳过已登记渠道主域名/别名，按同一分类器补建队列项，幂等。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\backfill_source_reviews.py --dry-run
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\backfill_source_reviews.py
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\backfill_source_reviews.py --project-code gz-base
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Project
from app.services.source_review_backfill import backfill_source_reviews


def main() -> int:
    parser = argparse.ArgumentParser(description="补建历史引用的未知域名审核队列")
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

        total_created = 0
        for project in projects:
            result = backfill_source_reviews(db, project.id, dry_run=args.dry_run)
            if not args.dry_run:
                db.commit()
            total_created += result["created"]
            print(
                f"{project.code}: 引用域名 {result['domains']} 个，已登记渠道域名 "
                f"{result['registered']} 个，待补建 {result['candidates']} 个，"
                f"本次新建 {result['created']} 个"
            )
        mode = "预演（未写库）" if args.dry_run else "已写库"
        print(f"合计新建 {total_created} 个未知域名队列项；{mode}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
