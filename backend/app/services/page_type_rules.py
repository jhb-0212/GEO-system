"""引用页型规则重判：把 `page_type = other` 的那一半引用救回来。

为什么先做规则而不是模型：

1. 引用 URL 自带强信号（`/question/`、`/article/`、`/rank/`、`douyin` 域名……），规则足够解释；
2. 规则可枚举、可复核、可回归测试；模型判错无法向客户解释；
3. 只改「当前是 other / 来源未知」的行，**不动人工改过的行**（`page_type_source = manual` 永远跳过），
   也不动已经是 `rule` 判出来的非 other 行（除非显式要求重判）。

每条判定都带 `rule` 与 `reason`，落库时写 `classification_rule_version`，便于以后回滚口径。
"""

import re
import uuid
from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import MonitoringCitation
from app.models.enums import CitationPageType

RULE_VERSION = "page-type-r1"

# 人工改过的页型永不动；其余 other 行（来源 rule / unknown / 空）都可以重判。
MANUAL_SOURCE = "manual"

VIDEO_HOSTS = ("douyin.com", "v.qq.com", "ixigua.com", "youtube.com", "bilibili.com", "kuaishou.com")
ARTICLE_HOSTS = ("mp.weixin.qq.com", "toutiao.com", "baijiahao.baidu.com", "csdn.net", "jianshu.com", "36kr.com")

PATH_RULES: list[tuple[str, CitationPageType, re.Pattern[str], str]] = [
    ("video", CitationPageType.VIDEO, re.compile(r"(/video/|/v/|/watch|/play/|/douyin/)", re.I), "路径含 video/watch/play"),
    ("forum_or_qa", CitationPageType.FORUM_OR_QA, re.compile(r"(/question|/answer|/qa|/forum|/thread|/discussion|/ask)", re.I), "路径含 question/answer/qa/forum/thread"),
    ("listicle", CitationPageType.LISTICLE, re.compile(r"(/top[-_]?|/rank|/ranking|/paihang|/bang|/best[-_]|/list/|/listicle)", re.I), "路径含 top/rank/bang/list"),
    ("comparison", CitationPageType.COMPARISON, re.compile(r"(/compare|/vs[-_]|/versus|/duibi|/dui[-_]?bi)", re.I), "路径含 compare/vs/对比"),
    ("review", CitationPageType.REVIEW, re.compile(r"(/review|/pingce|/pingjia|/comment|/koubei|/rating)", re.I), "路径含 review/评测/口碑"),
    ("how_to", CitationPageType.HOW_TO, re.compile(r"(/how[-_]?to|/guide|/tutorial|/jiaocheng|/gonglue|/step)", re.I), "路径含 how-to/guide/tutorial"),
    ("faq", CitationPageType.FAQ, re.compile(r"(/faq|/help|/questions[-_]?and)", re.I), "路径含 faq/help"),
    ("admissions", CitationPageType.ADMISSIONS, re.compile(r"(/admission|/zhaosheng|/zsxx|/enroll)", re.I), "路径含 admission/招生"),
    ("recruitment", CitationPageType.RECRUITMENT, re.compile(r"(/job|/jobs|/recruit|/zhaopin|/hr/)", re.I), "路径含 job/recruit/招聘"),
    ("case_study", CitationPageType.CASE_STUDY, re.compile(r"(/case|/cases|/anli|/story/)", re.I), "路径含 case/anli"),
    ("course_or_product", CitationPageType.COURSE_OR_PRODUCT, re.compile(r"(/course|/product|/goods|/sku|/item/|/detail)", re.I), "路径含 course/product/goods/detail"),
    ("search_surface", CitationPageType.SEARCH_SURFACE, re.compile(r"(/search|/result|/so/)", re.I), "路径含 search/result"),
    ("article", CitationPageType.ARTICLE, re.compile(r"(/article|/news|/p/|/post|/blog|/zhuanlan|/note|/a/|/content)", re.I), "路径含 article/news/p/post/zhuanlan"),
]

TITLE_RULES: list[tuple[str, CitationPageType, re.Pattern[str]]] = [
    ("title:listicle", CitationPageType.LISTICLE, re.compile(r"(十大|排行榜|排名|盘点|榜单|推荐榜|哪家好|TOP\s?\d)", re.I)),
    ("title:comparison", CitationPageType.COMPARISON, re.compile(r"(对比|横评|哪家强|vs\.?)", re.I)),
    ("title:review", CitationPageType.REVIEW, re.compile(r"(评测|测评|口碑|怎么样|值不值|真实体验)", re.I)),
    ("title:how_to", CitationPageType.HOW_TO, re.compile(r"(教程|怎么|如何|指南|攻略|步骤)", re.I)),
    ("title:faq", CitationPageType.FAQ, re.compile(r"(常见问题|FAQ|答疑)", re.I)),
    ("title:admissions", CitationPageType.ADMISSIONS, re.compile(r"(招生|报名|简章)", re.I)),
    ("title:recruitment", CitationPageType.RECRUITMENT, re.compile(r"(招聘|岗位|招人)", re.I)),
    ("title:case", CitationPageType.CASE_STUDY, re.compile(r"(案例|学员故事|上岸经历)", re.I)),
]


def _host(url: str) -> str:
    try:
        netloc = (urlparse(url).netloc or "").lower()
    except ValueError:
        return ""
    return netloc[4:] if netloc.startswith("www.") else netloc


def _path(url: str) -> str:
    try:
        return urlparse(url).path or "/"
    except ValueError:
        return "/"


def infer_page_type(url: str | None, *, title: str | None = None, is_domain_level: bool = False) -> dict:
    """按 URL 路径 → 站点 → 标题的顺序判页型；判不出就老实返回 other。"""
    if is_domain_level:
        return {"page_type": CitationPageType.HOMEPAGE, "rule": "domain_level", "reason": "引用只到域名层级"}

    raw = (url or "").strip()
    if not raw:
        return {"page_type": CitationPageType.OTHER, "rule": "empty_url", "reason": "无 URL，无法判页型"}

    host = _host(raw)
    path = _path(raw)
    if host == "mp.weixin.qq.com":
        return {"page_type": CitationPageType.ARTICLE, "rule": "host:wechat_article", "reason": "公众号图文页（/s? 不是搜索页）"}
    if path in ("", "/"):
        return {"page_type": CitationPageType.HOMEPAGE, "rule": "path:root", "reason": "URL 只到站点根"}

    if ("zhihu.com" in host) and "/question" in path:
        return {"page_type": CitationPageType.FORUM_OR_QA, "rule": "host:zhihu_question", "reason": "知乎问题页"}
    for qa_host in ("zhidao.baidu.com", "wenda.so.com", "tieba.baidu.com"):
        if host == qa_host or host.endswith(f".{qa_host}"):
            return {"page_type": CitationPageType.FORUM_OR_QA, "rule": "host:qa", "reason": f"问答站 {qa_host}"}

    for host_pattern in VIDEO_HOSTS:
        if host == host_pattern or host.endswith(f".{host_pattern}"):
            return {"page_type": CitationPageType.VIDEO, "rule": "host:video", "reason": f"视频站 {host_pattern}"}

    searchable = f"{path}?{urlparse(raw).query}" if "?" in raw else path
    for rule, page_type, pattern, reason in PATH_RULES:
        if pattern.search(searchable):
            return {"page_type": page_type, "rule": f"path:{rule}", "reason": reason}

    for host_pattern in ARTICLE_HOSTS:
        if host == host_pattern or host.endswith(f".{host_pattern}"):
            return {"page_type": CitationPageType.ARTICLE, "rule": "host:article", "reason": f"图文站 {host_pattern}"}

    title_text = (title or "").strip()
    if title_text:
        for rule, page_type, pattern in TITLE_RULES:
            if pattern.search(title_text):
                return {"page_type": page_type, "rule": rule, "reason": f"标题命中「{pattern.pattern}」"}

    return {"page_type": CitationPageType.OTHER, "rule": "fallback:other", "reason": "路径与标题都无强信号"}



CONTENT_RULE_VERSION = "page-type-content-r1"

# 内容级词表：只认强信号词（权重 2），弱信号（1）单独出现不足以定档。
CONTENT_LEXICON: dict[CitationPageType, dict[str, int]] = {
    CitationPageType.LISTICLE: {"十大": 2, "排行": 2, "排名": 2, "盘点": 2, "榜单": 2, "哪家好": 2, "推荐": 1, "top": 2},
    CitationPageType.COMPARISON: {"对比": 2, "横评": 2, "哪个好": 2, "区别": 2, "vs": 2},
    CitationPageType.REVIEW: {"评测": 2, "测评": 2, "口碑": 2, "真实体验": 2, "值不值": 2, "避雷": 2},
    CitationPageType.HOW_TO: {"教程": 2, "指南": 2, "攻略": 2, "步骤": 2, "怎么": 1, "如何": 1, "流程": 1},
    CitationPageType.FAQ: {"常见问题": 2, "答疑": 2, "faq": 2},
    CitationPageType.ADMISSIONS: {"招生": 2, "报名": 2, "简章": 2},
    CitationPageType.RECRUITMENT: {"招聘": 2, "在招": 2, "职位描述": 2, "岗位职责": 2, "应聘": 2, "岗位": 1},
    CitationPageType.CASE_STUDY: {"案例": 2, "学员故事": 2, "上岸": 2},
    CitationPageType.COURSE_OR_PRODUCT: {"课程": 2, "培训班": 2, "学费": 2, "价格": 1, "套餐": 1, "培训": 2},
    CitationPageType.FORUM_OR_QA: {"提问": 2, "求助": 2, "有人知道": 2},
    CitationPageType.VIDEO: {"视频": 2, "讲解": 2, "直播回放": 2},
    CitationPageType.ARTICLE: {"原创": 1, "全文": 1, "详情": 1, "发布": 1},
}


def infer_page_type_from_content(*, title: str | None = None, snippet: str | None = None) -> dict:
    """用标题 + 摘要词表定档。要求最高分 ≥2 且领先次高分，避免弱词误判。"""
    text = f"{title or ''} {snippet or ''}".lower()
    # 「怎么样」是评价问法，不是操作教程；不去掉会把口碑类文章误判成 how_to
    for noise in ("怎么样", "怎樣", "怎麼辦", "怎么办"):
        text = text.replace(noise, " ")
    if not text.strip():
        return {"page_type": CitationPageType.OTHER, "rule": "content:empty", "reason": "没有标题与摘要"}

    scores: dict[CitationPageType, int] = {}
    hits: dict[CitationPageType, list[str]] = {}
    for page_type, lexicon in CONTENT_LEXICON.items():
        for keyword, weight in lexicon.items():
            if keyword.lower() in text:
                scores[page_type] = scores.get(page_type, 0) + weight
                hits.setdefault(page_type, []).append(keyword)

    if not scores:
        return {"page_type": CitationPageType.OTHER, "rule": "content:no_keyword", "reason": "标题与摘要无形态词"}

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    top_type, top_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    if top_score < 2 or top_score - runner_up < 1:
        return {
            "page_type": CitationPageType.OTHER,
            "rule": "content:ambiguous",
            "reason": f"最高分 {top_score}、次高 {runner_up}，证据不足",
        }
    return {
        "page_type": top_type,
        "rule": f"content:{top_type.value}",
        "reason": f"命中词 {'、'.join(hits[top_type])}（得分 {top_score}，次高 {runner_up}）",
    }


def _page_type_value(value) -> str:
    return getattr(value, "value", str(value))


def reclassify(
    db: Session,
    project_id: uuid.UUID,
    *,
    dry_run: bool = True,
    limit: int = 100,
    sample_limit: int = 20,
    mode: str = "path",
) -> dict:
    """重判 other 引用。dry_run 只出对照表，不写库。"""
    filters = [
        MonitoringCitation.project_id == project_id,
        MonitoringCitation.page_type == CitationPageType.OTHER,
        MonitoringCitation.page_type_source != MANUAL_SOURCE,
    ]
    total_targets = db.scalar(
        select(func.count()).select_from(MonitoringCitation).where(*filters)
    ) or 0
    rows = db.scalars(
        select(MonitoringCitation)
        .where(*filters)
        .order_by(MonitoringCitation.id)
        .limit(limit)
    ).all()

    version = CONTENT_RULE_VERSION if mode == "content" else RULE_VERSION
    changed = 0
    by_target: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    examples: list[dict] = []
    for row in rows:
        if mode == "content":
            verdict = infer_page_type_from_content(title=row.title, snippet=row.snippet)
        else:
            verdict = infer_page_type(row.raw_url, title=row.title, is_domain_level=row.is_domain_level)
        target = verdict["page_type"]
        if target == CitationPageType.OTHER:
            continue
        changed += 1
        key = _page_type_value(target)
        by_target[key] = by_target.get(key, 0) + 1
        by_rule[verdict["rule"]] = by_rule.get(verdict["rule"], 0) + 1
        if len(examples) < sample_limit:
            examples.append({
                "citation_id": str(row.id),
                "url": row.raw_url,
                "domain": row.domain,
                "title": row.title,
                "from": "other",
                "to": key,
                "rule": verdict["rule"],
                "reason": verdict["reason"],
            })
        if not dry_run:
            row.page_type = target
            row.page_type_source = "rule"
            row.classification_rule_version = version
            row.classified_at = datetime.now(UTC)

    if not dry_run:
        db.flush()

    return {
        "dry_run": dry_run,
        "rule_version": version,
        "mode": mode,
        "scope": {
            "candidates": total_targets,
            "scanned": len(rows),
            "changed": changed,
            "unchanged": len(rows) - changed,
        },
        "by_target": by_target,
        "by_rule": by_rule,
        "examples": examples,
        "notes": [
            "只重判 page_type=other 的行；人工改过页型（page_type_source=manual）的行永不覆盖。",
            "path 模式按 URL 路径 → 站点 → 标题命中；content 模式只读标题与摘要词表，要求最高分 ≥2 且领先次高分。",
            "判不出仍是 other——宁可不判，也不为了好看把长尾硬塞进某个形态。",
        ],
    }
