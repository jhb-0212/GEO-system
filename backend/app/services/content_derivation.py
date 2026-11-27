"""渠道改编的约束与合规检查。

规则只做「客观可判」的两件事：篇幅上限、是否允许外链。
需要配图/引用来源这类无法自动判定的，进 checklist 提示，不冒充通过/不通过。
这样渠道稿的检查结论能复现，不依赖人工口述口径。
"""

from __future__ import annotations

import re

LINK_PATTERN = re.compile(r"(https?://|www\.)", re.IGNORECASE)

# max_chars=None 表示不限；no_link 表示正文里不能出现外链（百科类平台）
CHANNEL_RULES: dict[str, dict] = {
    "own_site": {"label": "自有官网", "max_chars": None, "no_link": False, "visual": False, "sources": False},
    "content_platform": {"label": "内容平台", "max_chars": 2000, "no_link": False, "visual": True, "sources": False},
    "video": {"label": "视频平台", "max_chars": 800, "no_link": False, "visual": True, "sources": False},
    "community": {"label": "社区", "max_chars": 1500, "no_link": False, "visual": False, "sources": False},
    "encyclopedia": {"label": "百科", "max_chars": 2000, "no_link": True, "visual": False, "sources": True},
    "local_media": {"label": "地方媒体", "max_chars": 3000, "no_link": False, "visual": False, "sources": False},
    "industry_media": {"label": "行业媒体", "max_chars": 3000, "no_link": False, "visual": False, "sources": False},
    "b2b": {"label": "B2B 商贸平台", "max_chars": 3000, "no_link": False, "visual": False, "sources": False},
    "institution": {"label": "院校机构", "max_chars": 3000, "no_link": False, "visual": False, "sources": False},
}

UNKNOWN_RULE = {"label": "未识别渠道", "max_chars": None, "no_link": False, "visual": False, "sources": False}


def rule_for(category: str | None) -> dict:
    return CHANNEL_RULES.get(category or "", UNKNOWN_RULE)


def run_checks(body: str, category: str | None) -> list[dict]:
    """返回可存档的检查项：ok 为结论，detail 给依据（含实测数字）。"""
    rule = rule_for(category)
    length = len(body)
    checks: list[dict] = []

    if rule["max_chars"] is None:
        checks.append({
            "key": "length",
            "label": "篇幅",
            "ok": True,
            "detail": f"{length} 字 · 该渠道不限篇幅",
        })
    else:
        over = length > rule["max_chars"]
        checks.append({
            "key": "length",
            "label": "篇幅",
            "ok": not over,
            "detail": f"{length} 字 / 上限 {rule['max_chars']} 字" + ("，超出需压缩" if over else ""),
        })

    has_link = bool(LINK_PATTERN.search(body))
    if rule["no_link"] and has_link:
        checks.append({
            "key": "external_link",
            "label": "外链",
            "ok": False,
            "detail": "正文含外链，该渠道不接受外链，改为文字描述或站内引用",
        })
    else:
        checks.append({
            "key": "external_link",
            "label": "外链",
            "ok": True,
            "detail": "含外链" if has_link else "正文无外链",
        })

    if rule["visual"]:
        checks.append({
            "key": "visual",
            "label": "配图/封面",
            "ok": False,
            "detail": "该渠道需要配图或封面，素材请从素材库挂载后人工确认",
        })
    if rule["sources"]:
        checks.append({
            "key": "sources",
            "label": "引用来源",
            "ok": False,
            "detail": "该渠道要求可核查来源，需人工补充来源后再提交",
        })
    return checks


def all_ok(checks: list[dict]) -> bool:
    return all(check["ok"] for check in checks)
