"""把公开页登记中的报名 FAQ 入口临时指向公司官网 /contact/。

背景：官网暂无独立 FAQ 页；/contact/ 有联系方式、地址与在线留言，可先作为
报名咨询入口。等官网 FAQ 页上线后，用 --restore 删除这条临时登记，再登记真实页。

用法（仓库根目录，仅适用于广州基地）：
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\point_faq_page_to_contact.py --project-code gz-base --dry-run
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\point_faq_page_to_contact.py --project-code gz-base --apply
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\point_faq_page_to_contact.py --project-code gz-base --apply --restore
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Project, PublicPage
from app.models.enums import PagePublishStatus, PageType

DEFAULT_PROJECT_CODE = ""  # 必须显式传 --project-code，本脚本仅适用于广州基地
SLUG = "faq"
CONTACT_URL = "http://www.gdccai.com/contact/"
TITLE = "报名 FAQ（暂指向联系我们）"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-code", required=True, help="项目 code，必须显式指定；本脚本仅适用于广州基地")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--restore", action="store_true", help="删除临时 FAQ 登记")
    args = parser.parse_args()
    if args.apply and args.dry_run:
        parser.error("--apply 与 --dry-run 不能同时使用")

    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None:
            print(f"项目不存在：{args.project_code}")
            return 2
        page = db.scalar(
            select(PublicPage).where(PublicPage.project_id == project.id, PublicPage.slug == SLUG)
        )

        if args.restore:
            if page is None:
                print("OK：没有临时 FAQ 登记，无需删除")
                return 0
            print(f"BEFORE {page.slug}: {page.title} | {page.url}")
            print("APPLY -> 删除临时 FAQ 登记")
            if args.apply:
                db.delete(page)
                db.commit()
            print("完成")
            return 0

        if page is None:
            print(f"NOT FOUND：{SLUG}，将创建临时登记")
            print(f"{'APPLY' if args.apply else 'DRY '} -> {TITLE} | {CONTACT_URL}")
            if args.apply:
                page = PublicPage(
                    project_id=project.id,
                    slug=SLUG,
                    title=TITLE,
                    page_type=PageType.FAQ,
                    url=CONTACT_URL,
                    canonical_url=CONTACT_URL,
                    publish_status=PagePublishStatus.PUBLISHED,
                    in_sitemap=False,
                    http_status=200,
                    last_published_at=datetime.now(timezone.utc),
                )
                db.add(page)
                db.commit()
            print("完成")
            return 0

        print(f"BEFORE {page.slug}: {page.title} | {page.url}")
        if page.url == CONTACT_URL and page.title == TITLE:
            print("OK：已经是目标状态")
            return 0
        print(f"{'APPLY' if args.apply else 'DRY '} -> {TITLE} | {CONTACT_URL}")
        if args.apply:
            page.title = TITLE
            page.page_type = PageType.FAQ
            page.url = CONTACT_URL
            page.canonical_url = CONTACT_URL
            page.publish_status = PagePublishStatus.PUBLISHED
            page.in_sitemap = False
            page.http_status = 200
            page.last_published_at = datetime.now(timezone.utc)
            db.commit()
        print("完成")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
