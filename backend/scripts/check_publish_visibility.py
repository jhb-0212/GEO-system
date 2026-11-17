"""发布可见性检测：查每条发布回执的页面能不能被搜索引擎检索到。

口径（与 `services/publish_visibility.py` 一致）：
- 按回执 URL 的站点做 `site:` 限定，用文章标题作 query；
- 只有返回结果的 URL 与回执 URL **精确相等**（`url_key` 归一）才算命中；
- 上游失败写 `error_code`，不算"未收录"。本脚本只写 `publish_visibility_checks`，
  **不改任何渠道归因字段**。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\check_publish_visibility.py --project-code gz-base --dry-run
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\check_publish_visibility.py --project-code gz-base
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\check_publish_visibility.py --receipt-id <uuid>

凭据：读环境变量 `QIANFAN_API_KEY`（或 `.env`），不落库、不打印。
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from sqlalchemy import select

from app.core.credentials import read_credential_env
from app.db.session import SessionLocal
from app.models import Project
from app.services.publish_visibility import DEFAULT_CREDENTIAL_REF, check_project


def main() -> int:
    parser = argparse.ArgumentParser(description="检测发布回执的搜索可见性")
    parser.add_argument("--project-code", help="只处理该项目；与 --receipt-id 二选一")
    parser.add_argument("--receipt-id", action="append", help="只检测指定回执，可重复")
    parser.add_argument("--limit", type=int, help="最多检测几条回执（按回执时间倒序）")
    parser.add_argument("--top-k", type=int, default=10, help="每次搜索返回条数上限，默认 10")
    parser.add_argument("--dry-run", action="store_true", help="只打印结果不写库")
    args = parser.parse_args()

    api_key = read_credential_env(DEFAULT_CREDENTIAL_REF)
    if not api_key:
        print(f"环境变量 {DEFAULT_CREDENTIAL_REF} 未配置，无法调用千帆 AI 搜索。")
        return 1

    with SessionLocal() as db:
        if args.project_code:
            project = db.scalars(select(Project).where(Project.code == args.project_code)).first()
            if project is None:
                print(f"未找到项目：{args.project_code}")
                return 1
            project_ids = [project.id]
        else:
            project_ids = list(db.scalars(select(Project.id).order_by(Project.code)))
        if not project_ids:
            print("没有可检测的项目。")
            return 1

        receipt_ids = None
        if args.receipt_id:
            receipt_ids = []
            for raw in args.receipt_id:
                try:
                    receipt_ids.append(uuid.UUID(raw))
                except ValueError:
                    print(f"回执 ID 不是合法 UUID：{raw}")
                    return 1

        with httpx.Client(timeout=30.0) as client:
            for project_id in project_ids:
                summary = check_project(
                    db,
                    project_id,
                    client=client,
                    api_key=api_key,
                    limit=args.limit,
                    top_k=args.top_k,
                    dry_run=args.dry_run,
                    receipt_ids=receipt_ids,
                )
                if not args.dry_run:
                    db.commit()
                print(
                    f"项目 {project_id}：检测 {summary['checked']} 条 → "
                    f"命中 {summary['matched']}、未收录 {summary['unmatched']}、"
                    f"查询失败 {summary['failed']}"
                )
        print("预演（未写库）" if args.dry_run else "已写库")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
