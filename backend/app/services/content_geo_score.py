"""GEO 内容评分：六个分项独立评分，不合成总分，失分项定位到具体段落。

六个分项固定为：
- 答案前置：开头是否直接给结论，而不是铺垫；
- 问题匹配：是否围绕已关联问句与目标词作答；
- 实体完整：品牌、产品、区域/行业与唯一标识是否写清；
- 证据密度：事实、引用、来源标注，以及无来源数字；
- 结构可引用：标题、列表、问答、段落长度；
- 权威信号：外部引用、来源域名与机构/报告类信号。

另附一个独立的「内容完整性」提示（`completeness`）：只检查已关联问句是否答到点、
关联事实是否在正文出现，不合成总分，也不改变上面六个分项的分数。

设计边界：
- 不做总分，不做等级，不预测平台收录、排名或推荐；
- 所有判断都是确定性规则，低分项必须返回 `paragraph_index` + 原文摘录 + 字符区间；
- 评分不阻断提交，原有 `content_quality` 仍是唯一的提交前置质检。
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    BrandProfile,
    CompanyProfile,
    ContentItem,
    ContentVersion,
    ContentVersionKeyword,
    Keyword,
    Project,
    Question,
)
from app.services.content_links import version_links
from app.services.selling_points import selling_point_check

RULE_VERSION = "geo-content-score-v2"

HEADING_PATTERN = re.compile(r"^\s{0,3}(#{1,4})\s+\S")
LIST_LINE_PATTERN = re.compile(r"^\s*(?:[-*+]|\d+[.、])\s+\S|\|.+\|", re.MULTILINE)
QA_PATTERN = re.compile(
    r"^\s*(?:#{1,4}\s*)?(?:\*\*)?[^\n]{2,80}[？?]\s*(?:\*\*)?\s*$", re.MULTILINE
)
SOURCE_MARKER_PATTERN = re.compile(
    r"https?://|来源[:：]|出处[:：]|引自|数据来源|据.{0,24}(报告|统计|白皮书|数据|年报|公示|通报|问卷)"
)
AUTHORITY_PATTERN = re.compile(
    r"报告|白皮书|协会|认证|资质|获奖|媒体|统计|公示|研究院|大学|政府|标准|专利|论文"
)
CLAIM_NUMBER_PATTERN = re.compile(r"(?<!\d)(?:[1-9]\d{0,2}(?:\.\d+)?%|(?:\d{2,}[万千亿]?)|(?:0\.\d+))")
EXTERNAL_LINK_PATTERN = re.compile(r"https?://[^\s)）]+")
BOILERPLATE_PATTERN = re.compile(
    r"^(随着|近年来|在当今|众所周知|如今|当前，?[^。]{0,20}(发展|变化)|作为[^。]{0,20}的重要)"
)
WORD_PATTERN = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9]+")
QUESTION_STOPWORDS = re.compile(
    r"哪些|哪个|什么|怎么|如何|为什么|多少|是否|可以|需要|一般|推荐|靠谱|哪家|怎么样|吗|呢|的|了|与|和|或"
)
# 问句意图 → 正文里应该出现的“答到点”的信号。
# 这层只做确定性提示，不替代人工判断：命中信号不等于答对，没命中也不等于事实错误。
INTENT_RULES: tuple[tuple[str, re.Pattern[str], re.Pattern[str], str], ...] = (
    (
        "price",
        re.compile(r"价格|费用|多少钱|收费|学费|报价"),
        re.compile(r"[0-9]+(?:\.[0-9]+)?\s*(?:元|万|块|万元)|免费|面议"),
        "价格/费用题，正文没有价格数字、免费或收费口径",
    ),
    (
        "address",
        re.compile(r"地址|在哪|位置|校区|地点|门店|怎么去"),
        re.compile(r"省|市|区|县|路|街|号|大道|广场|中心|校区|地址|位于|地铁"),
        "地址/位置题，正文没有地址、区域或到达方式",
    ),
    (
        "contact",
        re.compile(r"电话|联系|微信|公众号|手机|咨询方式|怎么咨询"),
        re.compile(r"1[3-9]\d{9}|0\d{2,3}-?\d{7,8}|电话|微信|公众号|扫码|联系|咨询"),
        "联系方式题，正文没有电话、微信、公众号或咨询入口",
    ),
    (
        "duration",
        re.compile(r"多久|多长时间|周期|几个月|几天|课时|学时|学多久"),
        re.compile(r"(?:[0-9]+|[一二三四五六七八九十])\s*(?:天|周|个月|月|年|小时|课时|学时)"),
        "周期/时长题，正文没有可识别的时长",
    ),
    (
        "process",
        re.compile(r"怎么|如何|流程|步骤|怎么办|怎么选|怎么报名"),
        re.compile(r"第[一二三四五六七八九十0-9]+步|首先|然后|最后|流程|步骤|先.{0,12}再"),
        "流程/步骤题，正文没有步骤、顺序或操作路径",
    ),
    (
        "fit",
        re.compile(r"适合|能不能|可以吗|是否|靠谱|值得|哪家|推荐"),
        re.compile(r"适合|不适合|可以|不可以|需要|不需要|建议|条件|前提|仅限|推荐"),
        "适合/选择类问题，正文没有适合条件、边界或明确建议",
    ),
    (
        "comparison",
        re.compile(r"区别|对比|哪个好|相比|优势|劣势"),
        re.compile(r"区别|对比|相比|优势|劣势|不同|更适合|差异"),
        "对比题，正文没有比较维度、差异或结论",
    ),
    (
        "definition",
        re.compile(r"是什么|什么是|定义|含义|指什么"),
        re.compile(r"是指|指的是|定义为|意思是|是一种|即"),
        "定义题，正文没有定义句或解释句",
    ),
)


def _count_words(body: str) -> int:
    return len(WORD_PATTERN.findall(body))


def _plain(text: str) -> str:
    text = re.sub(r"^\s{0,3}#{1,4}\s+", "", text)
    text = re.sub(r"^\s*(?:[-*+]|\d+[.、])\s+", "", text)
    return text.replace("**", "").replace("|", " ").strip()


def _blocks(body: str) -> list[dict[str, Any]]:
    """按空行切段，保留原文偏移；标题也作为一个可定位段。"""
    blocks: list[dict[str, Any]] = []
    for match in re.finditer(r"(?s)(?:^|\n{2,})([^\n](?:.|\n)*?)(?=\n{2,}|$)", body or ""):
        raw = match.group(1)
        text = raw.strip()
        if not text:
            continue
        start = match.start(1) + (len(raw) - len(raw.lstrip()))
        end = start + len(text)
        heading = bool(HEADING_PATTERN.match(text))
        blocks.append(
            {
                "index": len(blocks) + 1,
                "text": text,
                "plain": _plain(text),
                "start": start,
                "end": end,
                "heading": heading,
                "list_lines": len(LIST_LINE_PATTERN.findall(text)),
                "qa": bool(QA_PATTERN.match(text)),
                "source_marker": bool(SOURCE_MARKER_PATTERN.search(text)),
                "numbers": len(CLAIM_NUMBER_PATTERN.findall(text)),
                "external_links": len(EXTERNAL_LINK_PATTERN.findall(text)),
            }
        )
    return blocks


def _excerpt(text: str, limit: int = 90) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def _locator(block: dict[str, Any] | None) -> dict[str, Any]:
    if block is None:
        return {
            "paragraph_index": 1,
            "excerpt": "正文为空",
            "char_start": 0,
            "char_end": 0,
        }
    return {
        "paragraph_index": block["index"],
        "excerpt": _excerpt(block["plain"]),
        "char_start": block["start"],
        "char_end": block["end"],
    }


def _issue(
    check_key: str,
    detail: str,
    block: dict[str, Any] | None,
    severity: str = "medium",
) -> dict[str, Any]:
    return {
        "check_key": check_key,
        "detail": detail,
        "severity": severity,
        **_locator(block),
    }


def _fallback(blocks: list[dict[str, Any]], content_blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    return content_blocks[0] if content_blocks else (blocks[0] if blocks else None)


def _check(
    key: str,
    label: str,
    points: int,
    max_points: int,
    detail: str,
    issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "points": points,
        "max_points": max_points,
        "ratio": round(points / max_points, 4) if max_points else 0,
        "ok": points >= max_points,
        "detail": detail,
        "issues": issues or [],
    }


def _dimension(
    key: str,
    label: str,
    hint: str,
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    score = sum(item["points"] for item in checks)
    issues = [
        issue
        for check in checks
        if check["points"] < check["max_points"]
        for issue in check["issues"]
    ]
    return {
        "key": key,
        "label": label,
        "score": score,
        "issues": issues,
        "low": score < 70,
        "hint": hint,
        "checks": checks,
    }


def _bigrams(text: str) -> set[str]:
    cleaned = QUESTION_STOPWORDS.sub("", re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text))
    return {cleaned[i:i + 2] for i in range(max(0, len(cleaned) - 1))}


def _question_covered(text: str, body: str) -> bool:
    grams = _bigrams(text)
    if not grams:
        return False
    return len(grams & _bigrams(body)) >= 2


def _detect_intent(text: str) -> tuple[str, re.Pattern[str], str] | None:
    for key, question_pattern, answer_pattern, detail in INTENT_RULES:
        if question_pattern.search(text):
            return key, answer_pattern, detail
    return None


def _normalise_for_match(text: str) -> str:
    return re.sub(r"\s+", "", text or "").casefold()


def _completeness_report(
    *,
    question_texts: list[str],
    fact_links: list[dict[str, Any]],
    body: str,
) -> dict[str, Any]:
    """内容完整性提示：问句是否答到点、关联事实是否被正文使用。

    边界：
    - 只看已关联问句和已关联事实，不对未关联的问题做“漏答”判断；
    - 问句先过关键词覆盖，再按意图检查答到点的信号；没有识别出意图的题只给关键词结论；
    - 事实只做字面出现检查，未出现不等于内容不完整，需人工确认该事实是否必须写；
    - 不合成总分，不影响六个分项。
    """
    body_cf = body.casefold()
    question_rows: list[dict[str, Any]] = []
    answered = 0
    keyword_only = 0
    for text in question_texts:
        text = (text or "").strip()
        if not text:
            continue
        intent = _detect_intent(text)
        covered = _question_covered(text, body)
        if not covered:
            status = "unanswered"
            detail = "关联问句的关键词在正文中没有形成有效回应"
        elif intent is None:
            status = "covered"
            detail = "已按关键词判断有回应；未识别出具体题型，需人工确认是否答全"
        else:
            key, answer_pattern, missing_detail = intent
            if answer_pattern.search(body_cf):
                status = "covered"
                detail = "已识别题型并出现对应答案信号"
            else:
                status = "keyword_only"
                detail = missing_detail
        if status == "covered":
            answered += 1
        elif status == "keyword_only":
            keyword_only += 1
        question_rows.append(
            {
                "title": text,
                "status": status,
                "intent": intent[0] if intent else "general",
                "detail": detail,
            }
        )

    checkable_facts = [
        link for link in fact_links
        if isinstance(link.get("fact_value"), str) and len(link["fact_value"].strip()) >= 2
    ]
    used_facts = [link for link in checkable_facts if _normalise_for_match(link["fact_value"]) in _normalise_for_match(body)]
    unused_facts = [
        {
            "fact_key": link.get("fact_key"),
            "fact_type": link.get("fact_type"),
            "fact_value": link.get("fact_value"),
            "stale": bool(link.get("stale")),
        }
        for link in checkable_facts
        if link not in used_facts
    ][:10]

    if not question_rows:
        status = "no_questions"
    elif answered == len(question_rows):
        status = "ok"
    elif answered or keyword_only:
        status = "partial"
    else:
        status = "missing"

    return {
        "status": status,
        "questions_total": len(question_rows),
        "questions_answered": answered,
        "questions": question_rows[:10],
        "facts_total": len(fact_links),
        "facts_used": len(used_facts),
        "facts_unused": unused_facts,
        "notes": [
            "完整性只检查已关联问句与已关联事实；未关联的问题不计入漏答。",
            "问句按题型检查“答到点”的信号，命中信号不等于答对，仍建议人工复核。",
            "关联事实只做字面出现检查；未出现不等于内容不完整，需确认该事实是否必须写进正文。",
            "本项独立提示，不合成总分，不改动六个分项的分数。",
        ],
    }


def _brand_terms(db: Session, project: Project) -> list[str]:
    terms = [project.name]
    brand = db.scalar(
        select(BrandProfile).where(
            BrandProfile.project_id == project.id,
            BrandProfile.is_active.is_(True),
        )
    )
    if brand is not None:
        terms.append(brand.canonical_name)
        terms.extend(brand.aliases or [])
    company = db.scalar(
        select(CompanyProfile).where(
            CompanyProfile.project_id == project.id,
            CompanyProfile.is_active.is_(True),
        )
    )
    if company is not None:
        if company.brand_name:
            terms.append(company.brand_name)
        for product in company.products or []:
            if isinstance(product, dict):
                name = str(product.get("name") or "").strip()
                if name:
                    terms.append(name)
    return [term.strip() for term in terms if term and term.strip()]


def _company_context(db: Session, project_id: uuid.UUID) -> dict[str, Any]:
    company = db.scalar(
        select(CompanyProfile).where(
            CompanyProfile.project_id == project_id,
            CompanyProfile.is_active.is_(True),
        )
    )
    brand = db.scalar(
        select(BrandProfile).where(
            BrandProfile.project_id == project_id,
            BrandProfile.is_active.is_(True),
        )
    )
    if company is None:
        return {
            "products": [],
            "context_terms": [],
            "identifiers": [],
            "owned_domains": list(brand.owned_domains or []) if brand is not None else [],
        }
    products = [
        str(product.get("name") or "").strip()
        for product in (company.products or [])
        if isinstance(product, dict) and str(product.get("name") or "").strip()
    ]
    context_terms = [*(company.industries or []), *(company.regions or [])]
    return {
        "products": products,
        "context_terms": [str(item).strip() for item in context_terms if str(item).strip()],
        "identifiers": list(brand.identifiers or []) if brand is not None else [],
        "owned_domains": list(brand.owned_domains or []) if brand is not None else [],
    }


def _linked_keywords(db: Session, version_id: uuid.UUID) -> list[str]:
    names = db.scalars(
        select(Keyword.name)
        .join(ContentVersionKeyword, ContentVersionKeyword.keyword_id == Keyword.id)
        .where(ContentVersionKeyword.version_id == version_id)
        .order_by(Keyword.priority, Keyword.name)
    ).all()
    return [str(name).strip() for name in names if str(name).strip()]


def _linked_questions(db: Session, question_ids: list[uuid.UUID]) -> list[str]:
    if not question_ids:
        return []
    titles = db.scalars(select(Question.title).where(Question.id.in_(question_ids))).all()
    return [str(title).strip() for title in titles if str(title).strip()]


def score_content_geo(
    *,
    title: str,
    body: str,
    question_texts: list[str],
    keyword_names: list[str],
    citation_count: int,
    fact_links: list[dict[str, Any]],
    brand_terms: list[str],
    product_terms: list[str],
    context_terms: list[str],
    identifier_terms: list[str],
    owned_domains: list[str],
) -> dict[str, Any]:
    """纯函数评分：返回六个独立分项，不返回总分或等级。"""
    body = body or ""
    title = title or ""
    blocks = _blocks(body)
    content_blocks = [item for item in blocks if not item["heading"]]
    fallback = _fallback(blocks, content_blocks)
    opening = content_blocks[0] if content_blocks else None
    body_cf = body.casefold()
    title_cf = title.casefold()
    words = _count_words(body)
    brand_hits = sum(body_cf.count(term.casefold()) for term in brand_terms if term)
    brand_block = next(
        (item for item in content_blocks if any(term.casefold() in item["plain"].casefold() for term in brand_terms)),
        None,
    )
    keyword_hits = [name for name in keyword_names if name.casefold() in body_cf]
    approved_facts = [link for link in fact_links if not link.get("stale")]
    stale_facts = len(fact_links) - len(approved_facts)
    first_two = content_blocks[:2]
    first_two_hit = any(
        any(term.casefold() in item["plain"].casefold() for term in [*brand_terms, *keyword_names, *product_terms])
        for item in first_two
    )
    heading_count = sum(1 for item in blocks if item["heading"])
    list_lines = sum(item["list_lines"] for item in blocks)
    qa_count = sum(1 for item in blocks if item["qa"])
    long_blocks = [item for item in content_blocks if len(item["plain"]) > 280]
    source_marker_blocks = [item for item in blocks if item["source_marker"]]
    unsourced_number_blocks = [
        item for item in content_blocks
        if item["numbers"] > 0 and not item["source_marker"]
    ]
    authority_blocks = [item for item in blocks if AUTHORITY_PATTERN.search(item["plain"])]
    external_link_blocks = [item for item in blocks if item["external_links"] > 0]
    external_links = sum(item["external_links"] for item in blocks)
    owned_domain_hit = any(domain.casefold() in body_cf for domain in owned_domains if domain)
    product_hit = any(term.casefold() in body_cf for term in product_terms)
    context_hit = any(term.casefold() in body_cf for term in context_terms)
    identifier_hit = any(term.casefold() in body_cf for term in identifier_terms)
    product_block = next(
        (item for item in content_blocks if any(term.casefold() in item["plain"].casefold() for term in product_terms)),
        None,
    )
    context_block = next(
        (item for item in content_blocks if any(term.casefold() in item["plain"].casefold() for term in context_terms)),
        None,
    )
    identifier_block = next(
        (item for item in content_blocks if any(term.casefold() in item["plain"].casefold() for term in identifier_terms)),
        None,
    )
    last_block = content_blocks[-1] if content_blocks else fallback

    # 1. 答案前置
    opening_len = len(opening["plain"]) if opening else 0
    opening_points = 45 if 30 <= opening_len <= 220 else 25 if 1 <= opening_len < 30 else 15 if opening_len > 220 else 0
    opening_issues = []
    if opening_points < 45:
        if opening_len == 0:
            detail = "正文没有可识别的首段，无法判断是否先给结论"
        elif opening_len < 30:
            detail = f"首段仅 {opening_len} 字，信息不足以直接回答核心问题"
        else:
            detail = f"首段 {opening_len} 字，结论被铺垫拉长"
        opening_issues.append(_issue("opening_direct", detail, opening, "high" if opening_points == 0 else "medium"))

    boilerplate = bool(opening and BOILERPLATE_PATTERN.search(opening["plain"]))
    boiler_points = 0 if boilerplate else 25
    boiler_issues = [_issue("opening_boilerplate", "开头使用“随着/近年来/众所周知”等铺垫句，核心结论被推迟", opening)] if boilerplate else []

    front_points = 30 if first_two_hit else 0
    front_issues = [] if first_two_hit else [
        _issue("core_in_first_two", "前两段没有出现品牌、产品名或目标词，答案主体被推到后文", opening and first_two[0] if first_two else fallback)
    ]
    answer_frontload = _dimension(
        "answer_frontload",
        "答案前置",
        "读者和抽取模型只看开头几段时，能不能直接拿到结论。",
        [
            _check("opening_direct", "首段直接作答", opening_points, 45, f"首段 {opening_len} 字；建议 30–220 字内给出结论", opening_issues),
            _check("opening_boilerplate", "无空话铺垫", boiler_points, 25, "开头不铺陈行业背景或套话", boiler_issues),
            _check("core_in_first_two", "核心信息在前两段", front_points, 30, "前两段至少出现品牌、产品名或目标词", front_issues),
        ],
    )

    # 2. 问题匹配
    linked_count = len(question_texts)
    link_points = 35 if linked_count >= 3 else 24 if linked_count == 2 else 12 if linked_count == 1 else 0
    link_issues = []
    if link_points < 35:
        link_issues.append(_issue(
            "question_links",
            f"仅关联 {linked_count} 道题；建议至少关联 3 道覆盖同一意图的问句",
            fallback,
            "high" if linked_count == 0 else "medium",
        ))
    covered_questions = [text for text in question_texts if _question_covered(text, body)]
    coverage_points = 25 if linked_count and len(covered_questions) == linked_count else 15 if covered_questions else 0
    coverage_issues = []
    if coverage_points < 25:
        uncovered = [text for text in question_texts if text not in covered_questions][:3]
        if not question_texts:
            coverage_issues.append(_issue("question_coverage", "没有关联问句，无法检查是否逐题作答", fallback))
        else:
            for text in uncovered:
                coverage_issues.append(_issue(
                    "question_coverage",
                    f"关联问句「{text}」的关键词在正文中没有形成有效回应",
                    fallback,
                ))
    keyword_points = 20 if len(keyword_hits) >= 2 else 10 if len(keyword_hits) == 1 else 0
    keyword_issues = [] if keyword_points == 20 else [
        _issue("keyword_hit", f"正文命中目标词 {len(keyword_hits)}/{len(keyword_names)} 个，建议至少 2 个", fallback)
    ]
    density_points = 20 if len(keyword_hits) >= 3 else 15 if len(keyword_hits) == 2 else 8 if len(keyword_hits) == 1 else 0
    density_issues = [] if density_points == 20 else [
        _issue("keyword_density", f"目标词命中 {len(keyword_hits)} 个；建议覆盖 3 个以上同义表达", fallback)
    ]
    question_match = _dimension(
        "question_match",
        "问题匹配",
        "这段内容是否真的在回答已关联的问句，而不是泛泛介绍。",
        [
            _check("question_links", "关联问句数量", link_points, 35, f"已关联 {linked_count} 道题", link_issues),
            _check("question_coverage", "逐题有回应", coverage_points, 25, f"{len(covered_questions)}/{linked_count} 道题在正文中有回应", coverage_issues),
            _check("keyword_hit", "目标词命中", keyword_points, 20, f"命中 {len(keyword_hits)} 个", keyword_issues),
            _check("keyword_density", "目标词覆盖广度", density_points, 20, f"命中 {len(keyword_hits)} 个", density_issues),
        ],
    )

    # 3. 实体完整
    title_brand_points = 25 if any(term.casefold() in title_cf for term in brand_terms) else 0
    title_brand_issues = [] if title_brand_points else [
        _issue("brand_in_title", "标题没有出现客户对外品牌名", opening or fallback)
    ]
    body_brand_points = 20 if brand_hits >= 2 else 10 if brand_hits == 1 else 0
    body_brand_issues = [] if body_brand_points == 20 else [
        _issue("brand_in_body", f"品牌在正文出现 {brand_hits} 次；建议至少 2 次并写明主体", brand_block or opening or fallback)
    ]
    product_points = 20 if product_hit else 0
    product_issues = [] if product_hit else [
        _issue("product_mention", "正文没有写出客户产品/服务名称，AI 难以把内容归到具体产品", product_block or opening or fallback)
    ]
    context_points = 15 if context_hit else 0
    context_issues = [] if context_hit else [
        _issue("context_identity", "正文没有写区域或行业，实体范围不明确", context_block or opening or fallback)
    ]
    identifier_points = 20 if identifier_hit or owned_domain_hit else 0
    identifier_issues = [] if identifier_points else [
        _issue("identifier_identity", "正文没有唯一标识（地址、电话、官网、公众号等）", identifier_block or last_block)
    ]
    entity = _dimension(
        "entity",
        "实体完整",
        "品牌、产品、区域和唯一标识写清楚，AI 才不会混淆主体。",
        [
            _check("brand_in_title", "标题含品牌", title_brand_points, 25, "标题直接写客户对外品牌名", title_brand_issues),
            _check("brand_in_body", "正文品牌出现", body_brand_points, 20, f"品牌正文出现 {brand_hits} 次", body_brand_issues),
            _check("product_mention", "产品/服务名称", product_points, 20, "至少写一个客户产品/服务名", product_issues),
            _check("context_identity", "区域或行业", context_points, 15, "至少写一个区域或行业", context_issues),
            _check("identifier_identity", "唯一标识", identifier_points, 20, "地址、电话、官网或公众号至少一项", identifier_issues),
        ],
    )

    # 4. 证据密度
    fact_points = 35 if len(approved_facts) >= 3 else 24 if len(approved_facts) == 2 else 12 if len(approved_facts) == 1 else 0
    fact_issues = [] if fact_points == 35 else [
        _issue("fact_links", f"可用事实 {len(approved_facts)} 条；建议至少 3 条，待处理 {stale_facts} 条", fallback, "high" if not approved_facts else "medium")
    ]
    citation_points = 25 if citation_count >= 3 else 17 if citation_count == 2 else 8 if citation_count == 1 else 0
    citation_issues = [] if citation_points == 25 else [
        _issue("citation_links", f"已关联人工确认引用 {citation_count} 条；建议至少 3 条", fallback, "high" if citation_count == 0 else "medium")
    ]
    marker_points = 20 if len(source_marker_blocks) >= 3 else 12 if source_marker_blocks else 0
    marker_issues = [] if marker_points == 20 else [
        _issue("source_markers", f"有来源标注的段落 {len(source_marker_blocks)} 个；建议至少 3 处", source_marker_blocks[0] if source_marker_blocks else fallback)
    ]
    unsourced_points = 0 if unsourced_number_blocks else 20
    unsourced_issues = [
        _issue("unsourced_numbers", f"本段有 {item['numbers']} 处数字，但同段没有来源标注", item)
        for item in unsourced_number_blocks[:3]
    ]
    evidence = _dimension(
        "evidence",
        "证据密度",
        "可回查的事实、引用与来源标注，是内容能被长期采用的基础。",
        [
            _check("fact_links", "关联已批准事实", fact_points, 35, f"可用 {len(approved_facts)} 条，待处理 {stale_facts} 条", fact_issues),
            _check("citation_links", "关联人工确认引用", citation_points, 25, f"已关联 {citation_count} 条", citation_issues),
            _check("source_markers", "正文来源标注", marker_points, 20, f"有来源标注的段落 {len(source_marker_blocks)} 个", marker_issues),
            _check("unsourced_numbers", "数字有来源", unsourced_points, 20, f"无来源数字段落 {len(unsourced_number_blocks)} 个", unsourced_issues),
        ],
    )

    # 5. 结构可引用
    heading_points = 25 if heading_count >= 2 else 12 if heading_count == 1 else 0
    heading_issues = [] if heading_points == 25 else [
        _issue("headings", f"标题层级 {heading_count} 个；建议至少 2 个二级标题", fallback)
    ]
    list_points = 20 if list_lines >= 2 else 10 if list_lines == 1 else 0
    list_issues = [] if list_points == 20 else [
        _issue("lists", f"列表/表格行 {list_lines} 条；建议把并列信息拆成列表", fallback)
    ]
    qa_points = 20 if qa_count >= 2 else 10 if qa_count == 1 else 0
    qa_issues = [] if qa_points == 20 else [
        _issue("qa_blocks", f"问句小标题 {qa_count} 个；建议把核心问题拆成独立问答", fallback)
    ]
    paragraph_points = 20 if not long_blocks else 0
    paragraph_issues = [
        _issue("paragraph_length", f"本段 {len(item['plain'])} 字，超过 280 字，不利于答案抽取", item)
        for item in long_blocks[:3]
    ]
    block_count_points = 15 if len(content_blocks) >= 4 else 8 if len(content_blocks) >= 2 else 0
    block_issues = [] if block_count_points == 15 else [
        _issue("block_count", f"有效段落 {len(content_blocks)} 个；建议至少 4 段拆开主题", last_block or fallback)
    ]
    structure = _dimension(
        "structure",
        "结构可引用",
        "标题、列表、问答与短段落，让答案抽取更稳定。",
        [
            _check("headings", "标题层级", heading_points, 25, f"标题 {heading_count} 个", heading_issues),
            _check("lists", "列表或表格", list_points, 20, f"列表/表格行 {list_lines} 条", list_issues),
            _check("qa_blocks", "问答块", qa_points, 20, f"问句小标题 {qa_count} 个", qa_issues),
            _check("paragraph_length", "段落长度", paragraph_points, 20, f"超长段落 {len(long_blocks)} 个", paragraph_issues),
            _check("block_count", "段落数量", block_count_points, 15, f"有效段落 {len(content_blocks)} 个", block_issues),
        ],
    )

    # 6. 权威信号
    authority_citation_points = 30 if citation_count >= 3 else 20 if citation_count == 2 else 10 if citation_count == 1 else 0
    authority_citation_issues = [] if authority_citation_points == 30 else [
        _issue("authority_citations", f"人工确认引用 {citation_count} 条；建议至少 3 条外部来源", fallback)
    ]
    external_points = 20 if external_links >= 2 else 10 if external_links == 1 else 0
    external_issues = [] if external_points == 20 else [
        _issue("external_links", f"正文外部链接 {external_links} 个；建议至少 2 个可核验来源", external_link_blocks[0] if external_link_blocks else fallback)
    ]
    authority_marker_points = 25 if len(authority_blocks) >= 2 else 12 if authority_blocks else 0
    authority_marker_issues = [] if authority_marker_points == 25 else [
        _issue("authority_markers", f"机构/报告/认证类信号出现在 {len(authority_blocks)} 个段落；建议至少 2 处", authority_blocks[0] if authority_blocks else fallback)
    ]
    owned_source_points = 15 if owned_domain_hit else 0
    owned_source_issues = [] if owned_source_points else [
        _issue("owned_source", "正文没有出现品牌自有域名或官网链接", fallback)
    ]
    authority_fact_points = 10 if approved_facts else 0
    authority_fact_issues = [] if authority_fact_points else [
        _issue("authority_facts", "没有关联已批准事实，权威信号无法回查", fallback)
    ]
    authority = _dimension(
        "authority",
        "权威信号",
        "外部引用、可核验链接与机构信号，决定这段内容能否被当作依据。",
        [
            _check("authority_citations", "外部引用", authority_citation_points, 30, f"已关联 {citation_count} 条", authority_citation_issues),
            _check("external_links", "可核验链接", external_points, 20, f"正文外链 {external_links} 个", external_issues),
            _check("authority_markers", "机构/报告信号", authority_marker_points, 25, f"相关段落 {len(authority_blocks)} 个", authority_marker_issues),
            _check("owned_source", "自有信源", owned_source_points, 15, "正文出现品牌自有域名或官网", owned_source_issues),
            _check("authority_facts", "权威事实", authority_fact_points, 10, f"已批准事实 {len(approved_facts)} 条", authority_fact_issues),
        ],
    )

    dimensions = [answer_frontload, question_match, entity, evidence, structure, authority]
    completeness = _completeness_report(
        question_texts=question_texts,
        fact_links=fact_links,
        body=body,
    )
    return {
        "rule_version": RULE_VERSION,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "dimensions": dimensions,
        "completeness": completeness,
        "attention_count": sum(1 for item in dimensions if item["low"]),
        "paragraph_count": len(blocks),
        "body_metrics": {
            "word_count": words,
            "paragraph_count": len(content_blocks),
            "heading_count": heading_count,
            "list_lines": list_lines,
            "qa_count": qa_count,
            "long_paragraphs": len(long_blocks),
            "brand_hits": brand_hits,
            "keyword_hits": len(keyword_hits),
            "fact_links": len(approved_facts),
            "stale_fact_links": stale_facts,
            "citation_links": citation_count,
            "external_links": external_links,
            "source_marker_paragraphs": len(source_marker_blocks),
            "unsourced_number_paragraphs": len(unsourced_number_blocks),
        },
        "disclaimer": "六项分项独立评估内容准备度，不合成总分，不预测、不保证任何平台的收录、排名或推荐结果。",
    }


def content_geo_score(
    db: Session,
    *,
    project: Project,
    item: ContentItem,
    version: ContentVersion,
) -> dict[str, Any]:
    links = version_links(db, version.id)
    keywords = _linked_keywords(db, version.id)
    questions = _linked_questions(db, links["question_ids"])
    context = _company_context(db, project.id)
    brand_terms = _brand_terms(db, project)
    return {
        **score_content_geo(
            title=item.title,
            body=version.body,
            question_texts=questions,
            keyword_names=keywords,
            citation_count=len(links["citation_ids"]),
            fact_links=links["fact_links"],
            brand_terms=brand_terms,
            product_terms=context["products"],
            context_terms=context["context_terms"],
            identifier_terms=context["identifiers"],
            owned_domains=context["owned_domains"],
        ),
        "version_id": str(version.id),
        "item_id": str(item.id),
        "content_hash": version.content_hash,
        "selling_points": selling_point_check(db, project.id, version.body),
    }
