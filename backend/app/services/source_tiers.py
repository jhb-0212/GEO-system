"""信源分级（T0–T3）与多源交叉验证。

两条边界，改代码前先看：

1. **分级是站点属性，不是内容质量分**。T0–T3 只回答"这个站在 AI 眼里算什么级别的信源"，
   由域名白名单 + 已有 `source_category` 推导，每条结论都带命中规则（`rule`），可逐条复核；
   不把分级加权成一个总分——那正是取舍清单里拒绝的合成分。
2. **交叉验证是计数，不是评级**。同一条回答里，我方被几个互相独立的站引用，这是事实；
   系统只给"单一来源 / 多来源 / 多高权重来源"三档计数和比率，不换算成"可信度得分"。

分级规则（顺序即优先级，先命中先生效）：

| 顺序 | 规则 | 判定 | 档位 |
|---|---|---|---|
| 1 | `owned_domain` | 命中 `brand_profiles.owned_domains` 或 `source_category=brand_owned` | T0 |
| 2 | `domain:gov_cn` / `domain:edu_cn` | `*.gov.cn`、`*.edu.cn` 后缀 | T0 |
| 3 | `category:institution:non_official_domain` | 标了政府/院校类别但域名不是 gov.cn/edu.cn（民办培训站就在这） | T2 |
| 4 | `whitelist:T1` | 高权重分发/强信源白名单（公众号、知乎、头条、抖音、百家号、小红书、B站、36氪、CSDN、搜狐） | T1 |
| 5 | `category:reference` | 百科/维基类参考站 | T1 |
| 6 | `whitelist:T2` | 垂类与门户（网易、腾讯、新浪、凤凰、中国教育在线、博客园、简书、豆瓣、多知网、Qinxue、百度百科词条页） | T2 |
| 7 | `default:T3` | 其余（长尾站、个人站、聚合采集站、未知） | T3 |

白名单是**显式常量**，加站要改代码并走一次提交——不做后台可编辑，避免"分级被运营随手调松"。
"""

import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BrandProfile, MonitoringCitation, MonitoringSample
from app.models.enums import CitationReviewStatus, SourceCategory

CONFIRMED = CitationReviewStatus.MANUAL_CONFIRMED
VALID_STATUSES = ("hit", "miss")

TIERS: dict[str, dict[str, str]] = {
    "T0": {
        "label": "一手权威",
        "definition": "品牌自有官网、政府/监管机构站、院校站。AI 引用这类站点通常代表事实性结论。",
    },
    "T1": {
        "label": "高权重信源",
        "definition": "国内大模型引用权重最高的一批分发平台与参考站（公众号、知乎、头条、抖音、百家号、小红书、B站、36氪、CSDN、搜狐、百科）。",
    },
    "T2": {
        "label": "垂类与门户",
        "definition": "行业垂类媒体、综合门户与知识社区。可被引用，但权重与稳定性低于 T1。",
    },
    "T3": {
        "label": "长尾与未知",
        "definition": "长尾站、个人站、聚合采集站与无法识别的域名。可以被引用，但不作为投放依据。",
    },
}

# 域名白名单：值即档位。匹配按"域名本身或父域"进行（mp.weixin.qq.com 命中 weixin.qq.com）。
WHITELIST: dict[str, str] = {
    # T1：大模型高频引用
    "weixin.qq.com": "T1",
    "zhihu.com": "T1",
    "toutiao.com": "T1",
    "douyin.com": "T1",
    "baijiahao.baidu.com": "T1",
    "xiaohongshu.com": "T1",
    "bilibili.com": "T1",
    "36kr.com": "T1",
    "csdn.net": "T1",
    "sohu.com": "T1",
    "baike.baidu.com": "T1",
    "wikipedia.org": "T1",
    # T2：垂类、门户、知识社区
    "163.com": "T2",
    "qq.com": "T2",
    "sina.com.cn": "T2",
    "sina.com": "T2",
    "ifeng.com": "T2",
    "eol.cn": "T2",
    "cnblogs.com": "T2",
    "jianshu.com": "T2",
    "douban.com": "T2",
    "duozhi.com": "T2",
    "qinxue365.com": "T2",
    "people.com.cn": "T2",
    "xinhuanet.com": "T2",
    "thepaper.cn": "T2",
    "jiemian.com": "T2",
    "huxiu.com": "T2",
}


def _normalize_domain(domain: str | None) -> str:
    value = (domain or "").strip().lower()
    if value.startswith("www."):
        value = value[4:]
    return value


def _host(url: str | None) -> str:
    if not url:
        return ""
    try:
        return _normalize_domain(urlparse(url).netloc or "")
    except ValueError:
        return ""


def _matches_family(domain: str, candidate: str) -> bool:
    return domain == candidate or domain.endswith(f".{candidate}")


_KNOWN_ROOTS = tuple(sorted(WHITELIST, key=len))


def family_key(domain: str | None) -> str:
    # 把子域折叠到同站主域：zhuanlan.zhihu.com 与 zhihu.com 视为一个信源。
    # 只按白名单已知主域折叠，未知域名原样返回——不对陌生域名做猜测式归并。
    key = _normalize_domain(domain)
    for candidate in _KNOWN_ROOTS:
        if key == candidate or key.endswith(f".{candidate}"):
            return candidate
    return key


def classify(
    domain: str | None,
    *,
    source_category: str | None = None,
    owned_domains: list[str] | None = None,
) -> dict:
    """给一个域名定档，返回档位与命中规则，便于逐条复核。"""
    key = _normalize_domain(domain)
    category = (source_category or "").strip().lower()

    if key and owned_domains:
        for owned in owned_domains:
            if _matches_family(key, _normalize_domain(owned)):
                return _result("T0", "owned_domain", f"命中自有域名 {owned}")

    if category == SourceCategory.BRAND_OWNED.value:
        return _result("T0", "category:brand_owned", "source_category = brand_owned")

    if key.endswith(".gov.cn") or key == "gov.cn":
        return _result("T0", "domain:gov_cn", "域名后缀 .gov.cn")
    if key.endswith(".edu.cn") or key == "edu.cn":
        return _result("T0", "domain:edu_cn", "域名后缀 .edu.cn")

    # 机构类别不等于一手权威：`education_institution` 里混着大量民办培训站
    # （求证/黑马/itcast 这类 .com 站），它们可以进 T2，但不能冒充 T0。
    if category in (
        SourceCategory.GOVERNMENT_INSTITUTION.value,
        SourceCategory.EDUCATION_INSTITUTION.value,
    ):
        return _result(
            "T2",
            "category:institution:non_official_domain",
            f"source_category = {category}，但域名非 .gov.cn/.edu.cn",
        )

    for candidate, tier in WHITELIST.items():
        if key and _matches_family(key, candidate):
            if tier == "T1" and category == SourceCategory.REFERENCE.value:
                return _result("T1", "category:reference", f"参考站（白名单 {candidate}）")
            return _result(tier, f"whitelist:{tier}", f"命中白名单 {candidate}")

    if category == SourceCategory.REFERENCE.value:
        return _result("T1", "category:reference", "source_category = reference")

    return _result("T3", "default:T3", "未命中白名单，按长尾处理")


def _result(tier: str, rule: str, reason: str) -> dict:
    meta = TIERS[tier]
    return {
        "tier": tier,
        "tier_label": meta["label"],
        "tier_definition": meta["definition"],
        "tier_rule": rule,
        "tier_reason": reason,
    }


def tier_rules() -> list[dict]:
    """对外暴露分级规则清单，验收时能对着这张表逐条核。"""
    return [
        {"order": 1, "rule": "owned_domain", "tier": "T0", "note": "自有域名（brand_profiles.owned_domains 或 source_category=brand_owned）"},
        {"order": 2, "rule": "domain:gov_cn|edu_cn", "tier": "T0", "note": "域名后缀 .gov.cn / .edu.cn"},
        {"order": 3, "rule": "category:institution:non_official_domain", "tier": "T2", "note": "标了政府/院校类别但域名非 .gov.cn/.edu.cn，不冒充一手权威"},
        {"order": 4, "rule": "whitelist:T1", "tier": "T1", "note": "大模型高频引用平台与参考站白名单"},
        {"order": 5, "rule": "category:reference", "tier": "T1", "note": "百科/维基类参考站"},
        {"order": 6, "rule": "whitelist:T2", "tier": "T2", "note": "垂类媒体与综合门户白名单"},
        {"order": 7, "rule": "default:T3", "tier": "T3", "note": "长尾、个人站、聚合站与未识别域名"},
    ]


def source_tiers(
    db: Session,
    project_id: uuid.UUID,
    *,
    days: int = 90,
    limit: int = 20,
    now: datetime | None = None,
) -> dict:
    """引用按站定档 + 多源交叉验证计数。分母口径与 M1 覆盖一致：只算已复核引用。"""
    moment = now or datetime.now(UTC)
    start_at = moment - timedelta(days=days)

    valid_ids = db.scalars(
        select(MonitoringSample.id).where(
            MonitoringSample.project_id == project_id,
            MonitoringSample.status.in_(VALID_STATUSES),
            MonitoringSample.sampled_at >= start_at,
        )
    ).all()

    brand_domains = db.scalar(
        select(BrandProfile.owned_domains).where(BrandProfile.project_id == project_id)
    ) or []
    owned = [_normalize_domain(item) for item in brand_domains if item]

    # 逐（域名, 回答, 竞品）取计数，再按同站主域在 Python 里聚合：
    # 同站的不同子域、不同页面折成一个信源，避免「同站多页」刷高域数与多源率。
    rows = db.execute(
        select(
            MonitoringCitation.domain,
            MonitoringCitation.sample_id,
            MonitoringCitation.competitor_id,
            func.max(MonitoringCitation.source_category),
            func.count(MonitoringCitation.id),
        )
        .select_from(MonitoringCitation)
        .where(
            MonitoringCitation.project_id == project_id,
            MonitoringCitation.sample_id.in_(valid_ids),
            MonitoringCitation.review_status == CONFIRMED,
        )
        .group_by(
            MonitoringCitation.domain,
            MonitoringCitation.sample_id,
            MonitoringCitation.competitor_id,
        )
    ).all()

    aggregated: dict[str, dict] = {}
    for domain, sample_id, competitor_id, source_category, count in rows:
        key = family_key(domain)
        bucket = aggregated.setdefault(key, {
            "domain": key,
            "citations": 0,
            "samples": set(),
            "competitor_citations": 0,
            "source_category": source_category or SourceCategory.UNKNOWN.value,
        })
        bucket["citations"] += int(count or 0)
        bucket["samples"].add(sample_id)
        if competitor_id is not None:
            bucket["competitor_citations"] += int(count or 0)
        # 保留更强的类别：自有/政府/院校优先，其次参考站，最后其他
        rank = {
            SourceCategory.BRAND_OWNED.value: 0,
            SourceCategory.GOVERNMENT_INSTITUTION.value: 0,
            SourceCategory.EDUCATION_INSTITUTION.value: 0,
            SourceCategory.REFERENCE.value: 1,
        }
        if rank.get(source_category or "", 2) < rank.get(bucket["source_category"], 2):
            bucket["source_category"] = source_category

    domains: list[dict] = []
    tier_stats = {tier: {"citations": 0, "domains": 0} for tier in TIERS}
    total_citations = 0
    for bucket in aggregated.values():
        entry = classify(bucket["domain"], source_category=bucket["source_category"], owned_domains=owned)
        tier_stats[entry["tier"]]["citations"] += bucket["citations"]
        tier_stats[entry["tier"]]["domains"] += 1
        total_citations += bucket["citations"]
        domains.append({
            "domain": bucket["domain"],
            "citations": bucket["citations"],
            "samples": len(bucket["samples"]),
            "competitor_citations": bucket["competitor_citations"],
            "source_category": bucket["source_category"],
            **entry,
        })
    domains.sort(key=lambda row: (-row["citations"], row["domain"]))

    # 交叉验证：以回答（sample）为单位，看这条回答里我方被几个互不相同的站引用。
    sample_rows = db.execute(
        select(MonitoringCitation.sample_id, MonitoringCitation.domain, MonitoringCitation.source_category)
        .select_from(MonitoringCitation)
        .where(
            MonitoringCitation.project_id == project_id,
            MonitoringCitation.sample_id.in_(valid_ids),
            MonitoringCitation.review_status == CONFIRMED,
            MonitoringCitation.competitor_id.is_(None),
        )
        .distinct()
    ).all()
    per_sample: dict[uuid.UUID, set[str]] = {}
    for sample_id, domain, source_category in sample_rows:
        key = family_key(domain)
        if not key:
            continue
        per_sample.setdefault(sample_id, set()).add(key)
    # 每条回答里我方的域名 → 档位（同一域名只算一次，避免同站多页刷高「多源」）
    tier_by_domain = {row["domain"]: row["tier"] for row in domains}
    sample_tiers: list[set[str]] = []
    for domain_list in per_sample.values():
        tiers_of_sample = set()
        for key in domain_list:
            tier = tier_by_domain.get(key)
            if tier:
                tiers_of_sample.add(tier)
            else:
                tiers_of_sample.add(classify(key, owned_domains=owned)["tier"])
        sample_tiers.append(tiers_of_sample)

    brand_cited = len(sample_tiers)
    single_source = sum(1 for domains_of_sample in per_sample.values() if len(domains_of_sample) == 1)
    multi_source = sum(1 for domains_of_sample in per_sample.values() if len(domains_of_sample) >= 2)
    tier01_supported = sum(1 for tiers_of_sample in sample_tiers if {"T0", "T1"} & tiers_of_sample)
    multi_high = sum(1 for tiers_of_sample in sample_tiers if len({"T0", "T1"} & tiers_of_sample) >= 2)

    tier_rows = [
        {
            "tier": tier,
            "label": meta["label"],
            "definition": meta["definition"],
            "domains": tier_stats[tier]["domains"],
            "citations": tier_stats[tier]["citations"],
            "citation_share": (
                round(tier_stats[tier]["citations"] / total_citations, 4) if total_citations else None
            ),
        }
        for tier, meta in TIERS.items()
    ]

    return {
        "days": days,
        "scope": {
            "valid_samples": len(valid_ids),
            "reviewed_citations": total_citations,
            "reviewed_domains": len(domains),
            "returned_domains": min(limit, len(domains)),
        },
        "tiers": tier_rows,
        "domains": domains[:limit],
        "cross_validation": {
            "brand_cited_answers": brand_cited,
            "single_source_answers": single_source,
            "multi_source_answers": multi_source,
            "tier01_supported_answers": tier01_supported,
            "multi_high_tier_answers": multi_high,
            "multi_source_rate": (round(multi_source / brand_cited, 4) if brand_cited else None),
            "multi_high_tier_rate": (round(multi_high / brand_cited, 4) if brand_cited else None),
        },
        "rules": tier_rules(),
        "notes": [
            "分级是站点属性：由域名白名单与 source_category 推导，每条带命中规则，可逐条复核。",
            "不做加权总分：分级只用于「该投哪一级」，不与提及率/引用率相乘。",
            "交叉验证按回答计数：同一站点的多个页面只算一个来源，避免同站多页刷高多源率。",
            "分母只算已复核（manual_confirmed）引用，且样本在近 N 天有效窗口内。",
        ],
    }
