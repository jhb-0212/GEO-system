"""引用来源分类：站点类别 + 页面类型，规则可解释、版本可追溯。

边界：
- 来源类别（source_category）回答“这个站是什么”，不等于“我们是否在该站发布过”；
- 页面类型（page_type）按 URL/标题判断，同一站点不同页面可以不同；
- 未知域名只进独立审核队列，绝不自动创建发布渠道。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BrandProfile, Channel, ChannelAlias, Competitor, PublicPage
from app.models.enums import CitationPageType, SourceCategory
from app.services.industry_presets import default_terms

# 分类规则版本：人工覆盖后，旧规则结果仍可解释
CLASSIFIER_VERSION = "citation-classifier-v2"

_DOMAIN_RULES: tuple[tuple[tuple[str, ...], SourceCategory], ...] = (
    (("zhihu.com", "xiaohongshu.com", "weibo.com", "douban.com", "tieba.baidu.com"), SourceCategory.SOCIAL_COMMUNITY),
    (("baijiahao.baidu.com", "toutiao.com", "sohu.com", "163.com", "qq.com", "sina.com.cn"), SourceCategory.CONTENT_PLATFORM),
    (("people.com.cn", "xinhuanet.com", "cctv.com", "chinadaily.com.cn", "thepaper.cn"), SourceCategory.NEWS_MEDIA),
    (("36kr.com", "iyiou.com", "huxiu.com", "tmtpost.com", "donews.com"), SourceCategory.INDUSTRY_MEDIA),
    (("gov.cn",), SourceCategory.GOVERNMENT_INSTITUTION),
    (("edu.cn",), SourceCategory.EDUCATION_INSTITUTION),
    (("wikipedia.org", "baike.baidu.com"), SourceCategory.REFERENCE),
    (("jd.com", "taobao.com", "tmall.com", "pinduoduo.com", "1688.com"), SourceCategory.ECOMMERCE),
    (("bilibili.com", "douyin.com", "kuaishou.com", "youtube.com"), SourceCategory.SOCIAL_COMMUNITY),
)

_TERMS = default_terms("page_type.citation_page_terms", {}) or {}
_PAGE_RULES: tuple[tuple[tuple[str, ...], CitationPageType], ...] = (
    (tuple(_TERMS.get("admissions", [])), CitationPageType.ADMISSIONS),
    (tuple(_TERMS.get("recruitment", [])), CitationPageType.RECRUITMENT),
    (("forum", "/question/", "thread", "tieba"), CitationPageType.FORUM_OR_QA),
    (("faq", "wenda"), CitationPageType.FAQ),
    (("listicle", "rank", "ranking", "best-", "/best", "top-", "paihang"), CitationPageType.LISTICLE),
    (("how-to", "howto", "guide", "tutorial", "jiaocheng"), CitationPageType.HOW_TO),
    (("compare", "comparison", "vs-", "-vs-", "duibi"), CitationPageType.COMPARISON),
    (("review", "pingce", "测评"), CitationPageType.REVIEW),
    (("case", "anli", "case-study"), CitationPageType.CASE_STUDY),
    (("video", "shipin"), CitationPageType.VIDEO),
    (("search", "so.", "/s?"), CitationPageType.SEARCH_SURFACE),
)


@dataclass(frozen=True)
class Classification:
    source_category: SourceCategory
    page_type: CitationPageType
    rule_version: str = CLASSIFIER_VERSION


def normalize_domain(value: str | None) -> str | None:
    if not value:
        return None
    host = value.strip().lower()
    if "://" in host:
        host = urlsplit(host).netloc
    host = host.split("@")[-1].split(":")[0].strip().strip(".")
    host = host.removeprefix("www.")
    return host or None


def classify_citation(*, domain: str | None, url: str, title: str | None = None) -> Classification:
    """按域名和 URL/标题做确定性分类；未知一律归 other/unknown，不猜品牌归属。"""
    host = normalize_domain(domain) or ""
    category = SourceCategory.UNKNOWN
    for suffixes, value in _DOMAIN_RULES:
        if any(host == suffix or host.endswith(f".{suffix}") for suffix in suffixes):
            category = value
            break
    else:
        if host:
            category = SourceCategory.OTHER

    path = urlsplit(url).path.lower().rstrip("/")
    haystack = f"{path} {(title or '').lower()}"
    page_type = CitationPageType.ARTICLE
    if not path:
        page_type = CitationPageType.HOMEPAGE
    elif any(token in haystack for token in ("/video", "bilibili.com", "douyin.com")):
        page_type = CitationPageType.VIDEO
    else:
        for tokens, value in _PAGE_RULES:
            if any(token in haystack for token in tokens):
                page_type = value
                break
        if page_type == CitationPageType.ARTICLE and any(
            token in haystack for token in ("/course", "/product", "/kc", "/class")
        ):
            page_type = CitationPageType.COURSE_OR_PRODUCT
    return Classification(source_category=category, page_type=page_type)


def known_domains(db: Session, project_id: uuid.UUID) -> set[str]:
    """项目已登记的域名：渠道主域/别名、公开页、品牌自有域、竞品域。"""
    domains: set[str] = set()
    for value in db.scalars(
        select(Channel.primary_domain).where(Channel.project_id == project_id)
    ):
        if value:
            domains.add(normalize_domain(value) or "")
    for value in db.scalars(
        select(ChannelAlias.domain).where(ChannelAlias.project_id == project_id)
    ):
        if value:
            domains.add(normalize_domain(value) or "")
    for url, canonical in db.execute(
        select(PublicPage.url, PublicPage.canonical_url).where(PublicPage.project_id == project_id)
    ):
        for value in (url, canonical):
            domain = normalize_domain(value)
            if domain:
                domains.add(domain)
    for owned in db.scalars(
        select(BrandProfile.owned_domains).where(
            BrandProfile.project_id == project_id, BrandProfile.is_active.is_(True)
        )
    ):
        for value in owned or []:
            domain = normalize_domain(str(value))
            if domain:
                domains.add(domain)
    for value in db.scalars(
        select(Competitor.domain).where(Competitor.project_id == project_id)
    ):
        if value:
            domains.add(normalize_domain(value) or "")
    domains.discard("")
    return domains


def manual_category_map(db: Session, project_id: uuid.UUID) -> dict[str, SourceCategory]:
    """人工已分类域名：后续自动分类必须让位。"""
    from app.models import CitationSourceReview
    from app.models.enums import SourceReviewStatus

    rows = db.execute(
        select(CitationSourceReview.domain, CitationSourceReview.source_category).where(
            CitationSourceReview.project_id == project_id,
            CitationSourceReview.status == SourceReviewStatus.CLASSIFIED,
            CitationSourceReview.source_category.isnot(None),
        )
    )
    return {
        normalize_domain(domain) or domain: category
        for domain, category in rows
        if domain
    }
