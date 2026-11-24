"""把已 approved 内容版本映射到公司官网页面（public_pages.content_item_id）。

背景（2026-11-17 决策）：geo 不做公开站，公开页统一由 `www.gdccai.com` 渲染；
`public_pages` 登记官网真实页面，`content_item_id` 只表示“该官网页面当前对应的
系统审核稿”，不改变官网内容，也不生成第二套公开页。

本脚本只做最小、可解释的映射：
- home / about / contact -> 基地介绍母稿（地址、电话、班型、实训方式）
- product（实训班列表） -> 选课渠道稿（如何选班型、看场地与项目）
- 具体课程页（product-show-98518/98519）与案例页不强行映射：
  官网已有独立原文，但系统内没有对应 approved 版本，不能用母稿冒充具体课程/案例。

用法（仓库根目录，仅适用于广州基地）：
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\link_public_page_content.py --project-code gz-base --dry-run
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\link_public_page_content.py --project-code gz-base --apply

幂等：已有相同 content_item_id 时跳过；不覆盖指向其他内容实体的页面，除非 --force。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import ContentItem, ContentVersion, Project, PublicPage
from app.models.enums import ContentKind, ContentStatus, PagePublishStatus

DEFAULT_PROJECT_CODE = ""  # 必须显式传 --project-code，本脚本的页面标题映射仅适用于广州基地

# slug -> (内容类型, 标题前缀)；标题前缀只用于在当前项目已 approved 内容中定位，不写死 UUID。
TARGETS = {
    "home": (ContentKind.MASTER, "广州AI数字人才就业实训基地"),
    "about": (ContentKind.MASTER, "广州AI数字人才就业实训基地"),
    "contact": (ContentKind.MASTER, "广州AI数字人才就业实训基地"),
    "product": (ContentKind.CHANNEL, "广州AI实训怎么选"),
}


def _approved_item(db, project_id, kind: ContentKind, title_prefix: str) -> ContentItem | None:
    items = db.scalars(
        select(ContentItem)
        .where(
            ContentItem.project_id == project_id,
            ContentItem.kind == kind,
            ContentItem.status == ContentStatus.APPROVED,
        )
        .order_by(ContentItem.created_at.desc())
    ).all()
    for item in items:
        if item.title.startswith(title_prefix) and item.current_version_id:
            version = db.get(ContentVersion, item.current_version_id)
            if version is not None and version.status == ContentStatus.APPROVED:
                return item
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-code", required=True, help="项目 code，必须显式指定；页面标题映射仅适用于广州基地")
    parser.add_argument("--apply", action="store_true", help="写入数据库；不加时只预览")
    parser.add_argument("--dry-run", action="store_true", help="只预览（默认行为，保留此开关便于脚本统一）")
    parser.add_argument("--force", action="store_true", help="覆盖已指向其他内容实体的页面")
    args = parser.parse_args()
    if args.apply and args.dry_run:
        parser.error("--apply 与 --dry-run 不能同时使用")

    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None:
            print(f"项目不存在：{args.project_code}")
            return 2

        resolved: dict[str, ContentItem] = {}
        for slug, (kind, prefix) in TARGETS.items():
            item = _approved_item(db, project.id, kind, prefix)
            if item is None:
                print(f"SKIP {slug}: 未找到 approved {kind.value} 内容（标题前缀：{prefix}）")
                continue
            resolved[slug] = item

        pages = db.scalars(
            select(PublicPage).where(
                PublicPage.project_id == project.id,
                PublicPage.publish_status == PagePublishStatus.PUBLISHED,
            )
        ).all()
        by_slug = {page.slug: page for page in pages}

        changed = 0
        for slug, item in resolved.items():
            page = by_slug.get(slug)
            if page is None:
                print(f"SKIP {slug}: 官网页面未登记")
                continue
            if page.content_item_id == item.id:
                print(f"OK   {slug}: 已映射 {item.title}")
                continue
            if page.content_item_id is not None and not args.force:
                print(f"SKIP {slug}: 已指向其他内容实体，未加 --force")
                continue
            print(f"{'APPLY' if args.apply else 'DRY '} {slug}: {item.title} -> {item.id}")
            if args.apply:
                page.content_item_id = item.id
                changed += 1

        if args.apply:
            db.commit()
        print(f"完成：{'写入' if args.apply else '预览'} {changed} 个页面")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
