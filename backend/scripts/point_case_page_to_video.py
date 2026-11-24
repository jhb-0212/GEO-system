"""把公开页登记中的案例入口临时指向公司官网 /video/。

背景：官网 /cases/ 目前是空页，/video/ 已有 3 个学员作品；P01 的案例入口
先用真实作品页承接，等官网 /cases/ 上线内容后再切回。

用法（仓库根目录，仅适用于广州基地）：
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\point_case_page_to_video.py --project-code gz-base --dry-run
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\point_case_page_to_video.py --project-code gz-base --apply
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\point_case_page_to_video.py --project-code gz-base --apply --restore
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Project, PublicPage

DEFAULT_PROJECT_CODE = ""  # 必须显式传 --project-code，本脚本仅适用于广州基地
SLUG = "cases"
VIDEO_URL = "http://www.gdccai.com/video/"
CASES_URL = "http://www.gdccai.com/cases/"
VIDEO_TITLE = "学员作品与案例（视频）"
CASES_TITLE = "案例列表"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-code", required=True, help="项目 code，必须显式指定；本脚本仅适用于广州基地")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--restore", action="store_true", help="切回官网 /cases/")
    args = parser.parse_args()
    if args.apply and args.dry_run:
        parser.error("--apply 与 --dry-run 不能同时使用")

    target_url = CASES_URL if args.restore else VIDEO_URL
    target_title = CASES_TITLE if args.restore else VIDEO_TITLE

    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None:
            print(f"项目不存在：{args.project_code}")
            return 2
        page = db.scalar(
            select(PublicPage).where(PublicPage.project_id == project.id, PublicPage.slug == SLUG)
        )
        if page is None:
            print(f"未登记案例页：{SLUG}")
            return 1

        print(f"BEFORE {page.slug}: {page.title} | {page.url}")
        if page.url == target_url and page.title == target_title and page.canonical_url == target_url:
            print("OK：已经是目标状态")
            return 0
        print(f"{'APPLY' if args.apply else 'DRY '} -> {target_title} | {target_url}")
        if args.apply:
            page.url = target_url
            page.canonical_url = target_url
            page.title = target_title
            db.commit()
        print("完成")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
