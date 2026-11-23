"""引用标题/摘要补齐：内容级页型判定需要标题，但多数引用只存了 URL。

只做「取回页面自带的标题」，不改页型判定结论；取不到就留空，绝不臆造。
- 只处理 title 为空的 `page_type=other` 且非人工标注的行；
- 逐条限流、整体分批，失败不覆盖已有标题；
- dry_run 只探测不改库，便于先看能补多少。
"""

from __future__ import annotations

import html
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.monitoring import CitationPageType, MonitoringCitation

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
DESC_RE = re.compile(
    r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]*content=["\'](.*?)["\']',
    re.IGNORECASE | re.DOTALL,
)
SUFFIX_SEP = re.compile(r"\s*[_|｜\-—–]\s*")
META_CHARSET_RE = re.compile(r'<meta[^>]+charset=["\']?([\w-]+)', re.IGNORECASE)


def decode_html(resp: httpx.Response) -> str:
    """按 header → meta → utf-8 → gb18030 的顺序解码，中文老站点常不带 charset。"""
    raw = resp.content[:MAX_BYTES]
    charset = ""
    content_type = resp.headers.get("content-type", "").lower()
    if "charset=" in content_type:
        charset = content_type.split("charset=")[-1].split(";")[0].strip()
    if not charset:
        match = META_CHARSET_RE.search(raw.decode("ascii", errors="ignore")[:2000])
        if match:
            charset = match.group(1).lower()
    candidates = ([charset] if charset else []) + ["utf-8", "gb18030"]
    for encoding in candidates:
        try:
            text = raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
        if text.count("\ufffd") <= 3:
            return text
    return raw.decode("utf-8", errors="ignore")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
MAX_BYTES = 2 * 1024 * 1024


@dataclass
class FetchResult:
    status: str  # ok / not_html / blocked / error
    title: str | None = None
    snippet: str | None = None
    detail: str | None = None


def clean_title(raw: str | None) -> str | None:
    if not raw:
        return None
    text = html.unescape(raw)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    # 站点名后缀（"_中科商务网"、"- 今日头条"）不影响形态词，去掉一段即可
    parts = [part.strip() for part in SUFFIX_SEP.split(text) if part.strip()]
    if len(parts) >= 2 and len(parts[0]) >= 6 and len(parts[-1]) <= 20:
        text = parts[0]
    return text[:200]


def parse_html(html_text: str) -> tuple[str | None, str | None]:
    title_match = TITLE_RE.search(html_text)
    title = clean_title(title_match.group(1)) if title_match else None
    desc_match = DESC_RE.search(html_text)
    snippet = clean_title(desc_match.group(1)) if desc_match else None
    if snippet and len(snippet) > 160:
        snippet = snippet[:160]
    return title, snippet


def fetch_title(url: str, timeout: float = 8.0) -> FetchResult:
    try:
        resp = httpx.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"},
        )
    except Exception as exc:  # noqa: BLE001 - 网络失败一律降级为 error
        return FetchResult(status="error", detail=type(exc).__name__)
    if resp.status_code in (401, 403, 429):
        return FetchResult(status="blocked", detail=str(resp.status_code))
    if resp.status_code != 200:
        return FetchResult(status="error", detail=str(resp.status_code))
    content_type = resp.headers.get("content-type", "")
    if content_type and "html" not in content_type.lower() and "text" not in content_type.lower():
        return FetchResult(status="not_html", detail=content_type[:40])
    body = decode_html(resp)
    title, snippet = parse_html(body)
    if not title:
        return FetchResult(status="not_html", detail="no_title")
    return FetchResult(status="ok", title=title, snippet=snippet)


def backfill_titles(
    db: Session,
    project_id,
    *,
    limit: int = 50,
    dry_run: bool = True,
    sample_limit: int = 20,
    fetcher: Callable[[str], FetchResult] = fetch_title,
    workers: int = 4,
    pause: float = 0.5,
) -> dict:
    rows = list(
        db.scalars(
            select(MonitoringCitation)
            .where(
                MonitoringCitation.project_id == project_id,
                MonitoringCitation.page_type == CitationPageType.OTHER,
                MonitoringCitation.page_type_source != "manual",
                MonitoringCitation.title.is_(None),
            )
            .order_by(MonitoringCitation.created_at.asc())
            .limit(limit)
        )
    )

    results: list[tuple[MonitoringCitation, FetchResult]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = []
        for row in rows:
            futures.append(pool.submit(fetcher, row.raw_url))
            if pause:
                time.sleep(pause)
        for row, future in zip(rows, futures):
            try:
                results.append((row, future.result()))
            except Exception as exc:  # noqa: BLE001
                results.append((row, FetchResult(status="error", detail=type(exc).__name__)))

    titled = 0
    by_status: dict[str, int] = {}
    examples: list[dict] = []
    for row, result in results:
        by_status[result.status] = by_status.get(result.status, 0) + 1
        if result.status != "ok" or not result.title:
            continue
        titled += 1
        if not dry_run:
            row.title = result.title
            if result.snippet and not row.snippet:
                row.snippet = result.snippet
        if len(examples) < sample_limit:
            examples.append(
                {
                    "raw_url": row.raw_url,
                    "title": result.title,
                    "snippet": result.snippet,
                    "status": result.status,
                }
            )

    if not dry_run:
        db.commit()

    return {
        "dry_run": dry_run,
        "scope": {"candidates": len(rows), "titled": titled, "untitled": len(rows) - titled},
        "by_status": by_status,
        "examples": examples,
        "notes": [
            "只补 title 为空的 other 行，补不到就留空，不做推测。",
            "401/403/429 记为 blocked，与回执可访问性口径一致（被拦不等于不存在）。",
            "补完标题后，content 模式的词表判定才有输入。",
        ],
    }
