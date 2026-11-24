"""把公司官网已有页面登记进 public_pages。

背景（2026-11-17 决策）：geo 不做公开站，对外页面归公司官网；本表从"我们自己的页面"
改为"公司官网真实页面的登记表"，供 content_plans.site_page_id 关联与 citations 归因。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\import_public_pages.py --project-code <项目code> --base-url <官网根地址> --dry-run
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\import_public_pages.py --project-code <项目code> --base-url <官网根地址>            # 写入
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\import_public_pages.py --project-code <项目code> --base-url <官网根地址> --update   # 覆盖已有行的标题/URL/类型

说明：
- 数据源是公司官网 sitemap.xml（默认 http，官网当前 https 证书与主机名不匹配，https 会校验失败）。
- 幂等：按 (project_id, slug) 判断，已存在则跳过（除非 --update）。
- 不做页面抓取重试风暴：逐页请求，失败只记录并跳过，不写半条数据。
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models import Project  # noqa: E402
from app.models.content import PublicPage  # noqa: E402
from app.models.enums import PagePublishStatus, PageType  # noqa: E402

DEFAULT_BASE_URL = ""  # 必须显式传 --base-url，避免把某个客户的官网当成默认目标
DEFAULT_PROJECT_CODE = ""  # 必须显式传 --project-code
SKIP_PATH_PREFIXES = ("/sitemap", "/feed", "/search", "/tag", "/login", "/admin")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
CANONICAL_RE = re.compile(
    r'<link[^>]+rel=["\']canonical["\'][^>]*href=["\']([^"\']+)["\']', re.IGNORECASE
)
LOC_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.IGNORECASE | re.DOTALL)

# 官网列表页没有 h1，title 又是整站模板串，直接用这段标记识别"模板标题"
GENERIC_TITLE_MARKERS = ("广东AI数字人才就业实训基地_AIGC实训",)
# 已知列表页的固定中文名，避免登记成 slug 或模板串
PATH_LABELS = {
    "/": "首页",
    "/about/": "公司介绍",
    "/contact/": "联系我们",
    "/product/": "实训班列表",
    "/news/": "资讯列表",
    "/cases/": "案例列表",
    "/video/": "视频列表",
}


def slug_from_path(path: str) -> str:
    """把 URL 路径转成项目内唯一 slug：/ → home，/a/b/show-1.html → a-b-show-1。"""
    trimmed = path.strip("/")
    if not trimmed:
        return "home"
    trimmed = re.sub(r"\.(html?|php|aspx)$", "", trimmed, flags=re.IGNORECASE)
    slug = re.sub(r"[^a-z0-9]+", "-", trimmed.lower()).strip("-")
    return (slug or "home")[:128]


def page_type_from_path(path: str, title: str = "") -> PageType:
    """按路径归类；未知一律 other。

    注意：不按标题里的"课程/培训班"猜类型——资讯稿标题常带这些词，
    会把 news 误判成 course（实测踩过：8 条资讯被归成 course）。
    """
    lowered = path.lower()
    if lowered.strip("/") == "":
        return PageType.HOME
    if "contact" in lowered or "lianxi" in lowered:
        return PageType.CONTACT
    if "faq" in lowered or "wenti" in lowered:
        return PageType.FAQ
    if "case" in lowered or "anli" in lowered:
        return PageType.CASE
    if any(word in lowered for word in ("admissions", "admission", "zsxx", "zhaosheng", "enroll")):
        return PageType.ADMISSIONS
    if any(word in lowered for word in ("recruitment", "recruit", "zhaopin", "/jobs", "/job/", "careers")):
        return PageType.RECRUITMENT
    # 官网的 /product/ 与 /product/show-*.html 就是实训班（课程）页
    if any(word in lowered for word in ("course", "kecheng", "peixun", "training", "product", "zhuanye")):
        return PageType.COURSE
    return PageType.OTHER


def plain_text(fragment: str) -> str:
    """去掉标签与多余空白，只留文本。"""
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", fragment)).strip()


def resolve_title(html: str, path: str) -> str:
    """标题优先级：h1 → 非模板的 <title> → 已知列表页中文名 → 路径。"""
    h1_match = H1_RE.search(html)
    if h1_match:
        text = plain_text(h1_match.group(1))
        if text:
            return text[:255]
    title_match = TITLE_RE.search(html)
    if title_match:
        text = plain_text(title_match.group(1))
        if text and not any(marker in text for marker in GENERIC_TITLE_MARKERS):
            return text[:255]
    if path in PATH_LABELS:
        return PATH_LABELS[path]
    return path.strip("/") or "首页"


def fetch_text(client: httpx.Client, url: str) -> str | None:
    try:
        response = client.get(url, timeout=20.0)
    except httpx.HTTPError as exc:  # 网络问题只跳过这一页
        print(f"  跳过（请求失败）{url}：{type(exc).__name__}")
        return None
    if response.status_code != 200:
        print(f"  跳过（HTTP {response.status_code}）{url}")
        return None
    return response.text


def collect_urls(client: httpx.Client, sitemap_url: str, host: str) -> list[str]:
    text = fetch_text(client, sitemap_url)
    if text is None:
        raise SystemExit(f"无法读取 sitemap：{sitemap_url}")
    urls = [loc.strip() for loc in LOC_RE.findall(text)]
    kept: list[str] = []
    for url in urls:
        parsed = urlparse(url)
        if parsed.netloc and parsed.netloc != host:
            continue
        if any(parsed.path.startswith(prefix) for prefix in SKIP_PATH_PREFIXES):
            continue
        kept.append(url)
    return kept


def build_rows(client: httpx.Client, urls: list[str], base_url: str) -> list[dict]:
    rows: list[dict] = []
    for index, url in enumerate(urls, start=1):
        parsed = urlparse(url)
        path = parsed.path or "/"
        slug = slug_from_path(path)
        html = fetch_text(client, url)
        if html is None:
            continue
        title = resolve_title(html, path)
        canonical_match = CANONICAL_RE.search(html)
        canonical = canonical_match.group(1) if canonical_match else url
        page_type = page_type_from_path(path, title)
        rows.append(
            {
                "slug": slug,
                "title": title,
                "url": url,
                "canonical_url": canonical,
                "page_type": page_type,
            }
        )
        print(f"  [{index}/{len(urls)}] {slug} · {title[:48]}")
    return rows


def upsert_rows(project_code: str, rows: list[dict], update: bool, dry_run: bool) -> tuple[int, int, int]:
    inserted = updated = skipped = 0
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == project_code))
        if project is None:
            raise SystemExit(f"项目不存在：{project_code}")
        existing = {
            page.slug: page
            for page in db.scalars(select(PublicPage).where(PublicPage.project_id == project.id)).all()
        }
        now = datetime.now(UTC)
        for row in rows:
            current = existing.get(row["slug"])
            if current is None:
                inserted += 1
                if not dry_run:
                    db.add(
                        PublicPage(
                            project_id=project.id,
                            slug=row["slug"],
                            title=row["title"],
                            page_type=row["page_type"],
                            url=row["url"],
                            canonical_url=row["canonical_url"],
                            publish_status=PagePublishStatus.PUBLISHED,
                            last_published_at=now,
                        )
                    )
                continue
            if not update:
                skipped += 1
                continue
            changed = (
                current.title != row["title"]
                or current.url != row["url"]
                or current.canonical_url != row["canonical_url"]
                or current.page_type != row["page_type"]
            )
            if not changed:
                skipped += 1
                continue
            updated += 1
            if not dry_run:
                current.title = row["title"]
                current.url = row["url"]
                current.canonical_url = row["canonical_url"]
                current.page_type = row["page_type"]
                current.publish_status = PagePublishStatus.PUBLISHED
                current.last_published_at = now
        if dry_run:
            db.rollback()
        else:
            db.commit()
    return inserted, updated, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description="把公司官网页面登记进 public_pages")
    parser.add_argument("--project-code", required=True, help="项目 code，必须显式指定")
    parser.add_argument("--base-url", required=True, help="要登记的官网根地址，如 http://www.example.com")
    parser.add_argument("--sitemap-path", default="/sitemap.xml")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 条，0 表示全部")
    parser.add_argument("--update", action="store_true", help="覆盖已存在行的标题/URL/类型")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写库")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    host = urlparse(base_url).netloc
    sitemap_url = f"{base_url}{args.sitemap_path}"

    with httpx.Client(headers={"User-Agent": "geo-system-public-page-import/1.0"}) as client:
        print(f"读取 sitemap：{sitemap_url}")
        urls = collect_urls(client, sitemap_url, host)
        if args.limit:
            urls = urls[: args.limit]
        print(f"待登记页面 {len(urls)} 个")
        rows = build_rows(client, urls, base_url)

    inserted, updated, skipped = upsert_rows(args.project_code, rows, args.update, args.dry_run)
    prefix = "[dry-run] " if args.dry_run else ""
    print(
        f"{prefix}完成：解析 {len(urls)} 个 URL，新增 {inserted}、更新 {updated}、跳过 {skipped}"
        f"（项目 {args.project_code}）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
