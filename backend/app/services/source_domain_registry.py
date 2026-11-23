"""来源类别的站点级判定（域名身份表 + 人工队列）。

为什么改成按站点判：412 条已复核引用分布在 92 个站点，逐条判永远追不上；反过来，
一个站点的身份是稳定的（知乎是社区、百科是参考站、1688 是电商），判一次就能覆盖该站
全部引用。**判定依据只能是域名的身份事实，不能从标题/正文猜**——软文站那种"不知道算
什么"的，就进人工队列，不自动给类别。

三档状态：
- `settled`：该站已有已知类别（人工判过），无需再判；
- `suggested`：命中域名身份表，可一键采纳（每条都写明依据）；
- `needs_review`：身份不明，按被引条数排队等人工判。
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import CitationReviewStatus, SourceCategory
from app.models.monitoring import MonitoringCitation
from app.services.source_category_propagation import UNKNOWN_VALUES, site_key

CONFIRMED = CitationReviewStatus.MANUAL_CONFIRMED

# 域名身份表：只收「站点性质是公认事实」的域名，依据写在 reason 里。
# 判断口径是站点本身是什么，不是它上面某篇文章写了什么。
DOMAIN_IDENTITY: dict[str, tuple[str, str]] = {
    # 社区 / UGC
    "zhihu.com": ("social_community", "问答社区，内容由用户生产"),
    "xiaohongshu.com": ("social_community", "生活方式社区，UGC 笔记"),
    "douyin.com": ("social_community", "短视频社区，UGC"),
    "bilibili.com": ("social_community", "视频社区，UGC"),
    "tieba.baidu.com": ("social_community", "百度贴吧，UGC 论坛"),
    "douban.com": ("social_community", "兴趣社区，UGC 点评"),
    # 内容分发平台
    "weixin.qq.com": ("content_platform", "微信公众号，创作者内容分发"),
    "mp.weixin.qq.com": ("content_platform", "微信公众号文章页"),
    "toutiao.com": ("content_platform", "头条号内容分发"),
    "baijiahao.baidu.com": ("content_platform", "百家号内容分发"),
    "csdn.net": ("content_platform", "技术博客内容平台"),
    "jianshu.com": ("content_platform", "写作内容平台"),
    "gitcode.com": ("content_platform", "开源代码托管与内容平台"),
    "zhuanlan.zhihu.com": ("content_platform", "知乎专栏，创作者内容"),
    # 新闻 / 门户
    "sohu.com": ("news_media", "综合门户新闻"),
    "163.com": ("news_media", "综合门户新闻"),
    "sina.com.cn": ("news_media", "综合门户新闻"),
    "sina.com": ("news_media", "综合门户新闻"),
    "sina.cn": ("news_media", "综合门户新闻"),
    "southcn.com": ("news_media", "南方网，新闻机构网站"),
    "ifeng.com": ("news_media", "综合门户新闻"),
    "qq.com": ("news_media", "综合门户新闻"),
    "china.com": ("news_media", "综合门户新闻"),
    "people.com.cn": ("news_media", "中央新闻网站"),
    "xinhuanet.com": ("news_media", "国家通讯社网站"),
    "cctv.com": ("news_media", "中央广播电视总台网站"),
    "thepaper.cn": ("news_media", "新闻机构网站"),
    "jiemian.com": ("news_media", "财经新闻机构"),
    "yicai.com": ("news_media", "财经新闻机构"),
    "caixin.com": ("news_media", "财经新闻机构"),
    # 行业垂类媒体
    "36kr.com": ("industry_media", "科技创投资讯垂类"),
    "huxiu.com": ("industry_media", "科技商业资讯垂类"),
    "tmtpost.com": ("industry_media", "科技资讯垂类"),
    "iyiou.com": ("industry_media", "产业资讯垂类"),
    "eol.cn": ("industry_media", "教育行业资讯垂类"),
    "zhongjiaotong.com": ("industry_media", "教育行业资讯垂类"),
    "woshipm.com": ("industry_media", "产品/运营行业垂类社区"),
    # 参考站（含云厂商官方产品文档，属可直接核对的事实文档）
    "baike.baidu.com": ("reference", "百科参考站"),
    "cloud.baidu.com": ("reference", "云厂商官方产品文档"),
    "cloud.tencent.cn": ("reference", "云厂商官方产品文档"),
    "wikipedia.org": ("reference", "百科参考站"),
    "zh.wiktionary.org": ("reference", "词典参考站"),
    # 政府 / 公共机构
    "gov.cn": ("government_institution", "政府网站"),
    "edu.cn": ("government_institution", "教育机构/院校域名"),
    # 电商 / 交易平台
    "taobao.com": ("ecommerce", "电商交易平台"),
    "tmall.com": ("ecommerce", "电商交易平台"),
    "jd.com": ("ecommerce", "电商交易平台"),
    "1688.com": ("ecommerce", "B2B 交易平台"),
    "pinduoduo.com": ("ecommerce", "电商交易平台"),
    "b2b168.org": ("ecommerce", "B2B 供求信息平台"),
    "zk71.com": ("ecommerce", "B2B 供求信息平台"),
    "10100.com": ("ecommerce", "B2B 供求信息平台"),
}


def _identity(site: str) -> tuple[str, str] | None:
    """按域名本身或父域匹配身份表；不做模糊匹配。"""
    if site in DOMAIN_IDENTITY:
        return DOMAIN_IDENTITY[site]
    for root, value in DOMAIN_IDENTITY.items():
        if site.endswith(f".{root}"):
            return value
    return None


def domain_overview(
    db: Session,
    project_id: uuid.UUID,
    *,
    apply: bool = False,
    limit: int = 50,
) -> dict:
    rows = list(
        db.scalars(
            select(MonitoringCitation).where(
                MonitoringCitation.project_id == project_id,
                MonitoringCitation.review_status == CONFIRMED,
            )
        )
    )

    sites: dict[str, list[MonitoringCitation]] = defaultdict(list)
    for row in rows:
        sites[site_key(row.domain)].append(row)

    entries: list[dict] = []
    changed = 0
    for site, items in sites.items():
        known = defaultdict(int)
        for row in items:
            value = row.source_category.value if row.source_category else None
            if value and value not in UNKNOWN_VALUES:
                known[value] += 1
        pending = [
            row for row in items
            if not row.source_category or row.source_category.value in UNKNOWN_VALUES
        ]
        identity = _identity(site)
        if known:
            status = "settled"
            category, reason = max(known.items(), key=lambda kv: (kv[1], kv[0]))[0], "该站已有已知类别"
        elif identity:
            status = "suggested"
            category, reason = identity
        else:
            status = "needs_review"
            category, reason = None, "域名身份不在身份表内，需人工判定"

        wrote = 0
        if apply and status == "suggested" and pending:
            for row in pending:
                row.source_category = SourceCategory(category)
                wrote += 1
            changed += wrote

        entries.append(
            {
                "site": site,
                "citations": len(items),
                "pending": len(pending),
                "existing_categories": dict(known),
                "status": status,
                "suggested_category": category,
                "reason": reason,
                "written": wrote,
            }
        )

    if apply:
        db.commit()

    order = {"needs_review": 0, "suggested": 1, "settled": 2}
    entries.sort(key=lambda e: (order[e["status"]], -e["citations"]))
    total = len(rows)
    covered = sum(e["citations"] for e in entries if e["status"] != "needs_review")

    return {
        "apply": apply,
        "scope": {
            "citations": total,
            "sites": len(entries),
            "suggested_sites": sum(1 for e in entries if e["status"] == "suggested"),
            "needs_review_sites": sum(1 for e in entries if e["status"] == "needs_review"),
            "settled_sites": sum(1 for e in entries if e["status"] == "settled"),
            "citations_covered": covered,
            "changed": changed,
        },
        "domains": entries[:limit],
        "notes": [
            "按站点判一次、整站生效：'suggested' 只来自域名身份表，不看文章内容。",
            "身份表收录的是站点性质本身（社区/门户/百科/电商等），每条都带判定依据。",
            "'needs_review' 的站点按被引条数从多到少排队，先判影响最大的。",
        ],
    }
