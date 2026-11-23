"""官网 AI 爬虫诊断：L1 页面检查、L2 爬虫事件、L3 用户访问事件。

L1 只做技术可访问性事实采集，不生成修复建议；修复仍由官网负责。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.services.lead_visitors import hash_visitor

from app.models import (
    CrawlerEvent,
    Lead,
    MonitoringCitation,
    MonitoringSample,
    PublicPage,
    TrafficEvent,
)

_UA = "GEO-Diagnostics/1.0 (+https://www.gdccai.com)"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_MAX_HTML = 600_000
_MAX_SITEMAPS = 6


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _page_key(url: str) -> str:
    """页面匹配键：忽略 http/https 和末尾斜杠，避免台账与 CDN 日志因写法不同匹配失败。

    只用于 public_pages / crawler_events / citations 的页面归属匹配；
    canonical_ok 仍按 URL 全串比较，协议不一致仍视为 canonical 问题。
    """
    parts = urlsplit(url.strip())
    path = (parts.path or "/").rstrip("/") or "/"
    return urlunsplit(("", parts.netloc.lower(), path, parts.query, ""))


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.canonical: str | None = None
        self.script_count = 0
        self.text_chars = 0
        self._in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        if tag.lower() == "link" and "canonical" in values.get("rel", "").lower().split():
            self.canonical = values.get("href") or None
        elif tag.lower() == "script":
            self.script_count += 1
            self._in_script = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script":
            self._in_script = False

    def handle_data(self, data: str) -> None:
        if not self._in_script:
            self.text_chars += len(data.strip())


def _fetch(client: httpx.Client, url: str) -> httpx.Response | None:
    try:
        return client.get(url, follow_redirects=True)
    except httpx.HTTPError:
        return None


def _robots_allowed(client: httpx.Client, page_url: str) -> bool | None:
    robots_url = urljoin(page_url, "/robots.txt")
    response = _fetch(client, robots_url)
    if response is None:
        return None
    if response.status_code == 404:
        return True
    if response.status_code >= 400:
        return None
    path = urlsplit(page_url).path or "/"
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []
    for raw in response.text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            if agents:
                groups.append((agents, rules))
            agents, rules = [], []
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            agents.append(value.lower())
        elif key in {"allow", "disallow"} and value:
            rules.append((key, value))
    if agents:
        groups.append((agents, rules))

    relevant: list[tuple[str, str]] = []
    specific_groups = [
        group_rules
        for group_agents, group_rules in groups
        if "bytespider" in group_agents
    ]
    if specific_groups:
        for group_rules in specific_groups:
            relevant.extend(group_rules)
    else:
        for group_agents, group_rules in groups:
            if "*" in group_agents:
                relevant.extend(group_rules)
    if not relevant:
        return True

    def matches(rule: str) -> bool:
        anchored = rule.endswith("$")
        pattern = rule[:-1] if anchored else rule
        regex = "^" + "".join(
            ".*" if char == "*" else re.escape(char) for char in pattern
        )
        if anchored:
            regex += "$"
        return re.match(regex, path) is not None

    matched = [
        (len(rule), kind)
        for kind, rule in relevant
        if matches(rule)
    ]
    if not matched:
        return True
    longest = max(length for length, _ in matched)
    return any(kind == "allow" and length == longest for length, kind in matched)


def _sitemap_urls(client: httpx.Client, page_url: str) -> set[str] | None:
    sitemap_url = urljoin(page_url, "/sitemap.xml")
    response = _fetch(client, sitemap_url)
    if response is None:
        return None
    if response.status_code == 404:
        return set()
    if response.status_code >= 400:
        return None
    urls = {
        normalize_url(value)
        for value in re.findall(r"<loc>\s*(.*?)\s*</loc>", response.text, re.I | re.S)
    }
    child_sitemaps = [url for url in urls if url.lower().endswith(".xml")][:_MAX_SITEMAPS]
    for child in child_sitemaps:
        child_response = _fetch(client, child)
        if child_response is None or child_response.status_code >= 400:
            continue
        urls.update(
            normalize_url(value)
            for value in re.findall(
                r"<loc>\s*(.*?)\s*</loc>", child_response.text, re.I | re.S
            )
        )
    return urls


def check_public_page(page: PublicPage) -> dict:
    """抓取页面并返回 L1 检查结果；网络失败时只写 check_error，不伪造状态。"""
    result: dict = {
        "robots_allowed": None,
        "in_sitemap": None,
        "canonical_ok": None,
        "http_status": None,
        "js_dependent": None,
        "checked_at": datetime.now(timezone.utc),
        "check_error": None,
    }
    try:
        with httpx.Client(headers={"User-Agent": _UA}, timeout=_TIMEOUT) as client:
            response = client.get(page.url, follow_redirects=True)
            result["http_status"] = response.status_code
            html = response.text[:_MAX_HTML]
            parser = _PageParser()
            parser.feed(html)
            expected = normalize_url(page.canonical_url or page.url)
            result["canonical_ok"] = (
                normalize_url(urljoin(page.url, parser.canonical)) == expected
                if parser.canonical
                else False
            )
            result["js_dependent"] = parser.script_count > 0 and parser.text_chars < 200
            result["robots_allowed"] = _robots_allowed(client, page.url)
            sitemap_urls = _sitemap_urls(client, page.url)
            if sitemap_urls is None:
                result["in_sitemap"] = None
            else:
                candidates = {
                    normalize_url(page.url),
                    normalize_url(page.canonical_url or page.url),
                }
                result["in_sitemap"] = bool(candidates & sitemap_urls)
    except httpx.HTTPError as exc:
        result["check_error"] = str(exc)[:500]
    except Exception as exc:  # noqa: BLE001 - 检查失败必须落错误，不能阻断台账
        result["check_error"] = f"{type(exc).__name__}: {exc}"[:500]
    return result


def import_crawler_events(
    db: Session,
    project_id,
    events: list[dict],
    source: str | None,
) -> tuple[int, int]:
    page_by_url: dict[str, object] = {}
    for page in db.scalars(
        select(PublicPage).where(PublicPage.project_id == project_id)
    ).all():
        page_by_url[_page_key(page.url)] = page.id
        if page.canonical_url:
            page_by_url[_page_key(page.canonical_url)] = page.id

    matched: set[object] = set()
    for item in events:
        page_id = page_by_url.get(_page_key(item["page_url"]))
        if page_id is not None:
            matched.add(page_id)
        db.add(
            CrawlerEvent(
                project_id=project_id,
                public_page_id=page_id,
                page_url=item["page_url"],
                ua_claimed=item.get("ua_claimed"),
                source_ip=item.get("source_ip"),
                verified_bot=item.get("verified_bot", False),
                http_status=item.get("http_status"),
                bytes=item.get("bytes"),
                occurred_at=item["occurred_at"],
                import_source=item.get("import_source") or source,
            )
        )
    db.flush()
    return len(events), len(matched)


def import_traffic_events(
    db: Session,
    project_id,
    events: list[dict],
    source: str | None = None,
) -> int:
    for item in events:
        db.add(
            TrafficEvent(
                project_id=project_id,
                visitor_session_id=item.get("visitor_session_id"),
                # 只收原文、只存哈希：与 B4 线索访客同一套算法，保证同一 IP 在两处一致
                visitor_ip_hash=hash_visitor(item["visitor_ip"]) if item.get("visitor_ip") else None,
                visitor_region=item.get("visitor_region"),
                landing_url=item["landing_url"],
                utm_source=item.get("utm_source"),
                utm_campaign=item.get("utm_campaign"),
                referrer=item.get("referrer"),
                is_bot=item.get("is_bot", False),
                occurred_at=item["occurred_at"],
                import_source=item.get("import_source") or source,
            )
        )
    db.flush()
    return len(events)


def site_diagnostics_summary(db: Session, project_id) -> dict:
    pages = db.scalars(
        select(PublicPage).where(PublicPage.project_id == project_id)
    ).all()
    page_urls = {_page_key(page.url): page for page in pages}
    for page in pages:
        if page.canonical_url:
            page_urls.setdefault(_page_key(page.canonical_url), page)

    crawler_count = int(
        db.scalar(
            select(func.count()).select_from(CrawlerEvent).where(
                CrawlerEvent.project_id == project_id
            )
        )
        or 0
    )
    verified_count = int(
        db.scalar(
            select(func.count()).select_from(CrawlerEvent).where(
                CrawlerEvent.project_id == project_id,
                CrawlerEvent.verified_bot.is_(True),
            )
        )
        or 0
    )
    crawled_urls = {
        _page_key(url)
        for url in db.scalars(
            select(CrawlerEvent.page_url).where(
                CrawlerEvent.project_id == project_id,
                CrawlerEvent.verified_bot.is_(True),
            )
        ).all()
    }
    crawled_page_ids = {
        page.id for url, page in page_urls.items() if url in crawled_urls
    }

    citation_rows = db.execute(
        select(
            MonitoringCitation.normalized_url,
            MonitoringCitation.raw_url,
            MonitoringCitation.sample_id,
        ).where(MonitoringCitation.project_id == project_id)
    ).all()
    cited_page_ids: set[object] = set()
    page_sample_ids: dict[object, set[object]] = {}
    for normalized, raw, sample_id in citation_rows:
        for url in (normalized, raw):
            if not url:
                continue
            page = page_urls.get(_page_key(url))
            if page is not None:
                cited_page_ids.add(page.id)
                page_sample_ids.setdefault(page.id, set()).add(sample_id)
    mentioned_sample_ids = set(
        db.scalars(
            select(MonitoringSample.id).where(
                MonitoringSample.project_id == project_id,
                MonitoringSample.brand_mentioned.is_(True),
            )
        ).all()
    )

    buckets = {
        "crawlable_no_visit": sum(
            1
            for page in pages
            if page.robots_allowed is True
            and page.in_sitemap is True
            and page.id not in crawled_page_ids
        ),
        "visited_no_citation": sum(1 for page in pages if page.id in crawled_page_ids and page.id not in cited_page_ids),
        "cited_no_mention": sum(
            1
            for page in pages
            if page.id in cited_page_ids
            and not (page_sample_ids.get(page.id, set()) & mentioned_sample_ids)
        ),
        "visited_and_cited": sum(
            1 for page in pages if page.id in crawled_page_ids and page.id in cited_page_ids
        ),
    }

    traffic_count = int(
        db.scalar(
            select(func.count()).select_from(TrafficEvent).where(
                TrafficEvent.project_id == project_id
            )
        )
        or 0
    )
    bot_traffic_count = int(
        db.scalar(
            select(func.count()).select_from(TrafficEvent).where(
                TrafficEvent.project_id == project_id,
                TrafficEvent.is_bot.is_(True),
            )
        )
        or 0
    )
    session_count = int(
        db.scalar(
            select(func.count(func.distinct(TrafficEvent.visitor_session_id))).where(
                TrafficEvent.project_id == project_id,
                TrafficEvent.visitor_session_id.is_not(None),
                TrafficEvent.visitor_session_id != "",
            )
        )
        or 0
    )
    lead_session_count = int(
        db.scalar(
            select(func.count()).select_from(Lead).where(
                Lead.project_id == project_id,
                Lead.session_id.is_not(None),
                Lead.session_id != "",
            )
        )
        or 0
    )

    return {
        "pages_total": len(pages),
        "pages_checked": sum(1 for page in pages if page.checked_at is not None),
        "robots_blocked": sum(1 for page in pages if page.robots_allowed is False),
        "not_in_sitemap": sum(1 for page in pages if page.in_sitemap is False),
        "canonical_bad": sum(1 for page in pages if page.canonical_ok is False),
        "http_error": sum(
            1
            for page in pages
            if page.http_status is not None and page.http_status >= 400
        ),
        "js_dependent": sum(1 for page in pages if page.js_dependent is True),
        "crawler_events": crawler_count,
        "verified_bot_events": verified_count,
        "crawled_pages": len(crawled_page_ids),
        "traffic_events": traffic_count,
        "bot_traffic_events": bot_traffic_count,
        "visitor_sessions": session_count,
        "leads_with_session": lead_session_count,
        "buckets": buckets,
    }
