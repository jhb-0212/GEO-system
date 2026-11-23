"""内容提交前质检：在进审核队列之前把「必然被打回」的问题挡住。

只做能给出定位与依据的规则：
- 绝对化承诺（包就业/保过/100%…）——命中即 blocker，除非前文是否定表述；
- 残留模板占位 `{{槽位}}`——blocker，说明正文没填完就提交；
- 正文里的手机号没在「对外渠道」登记——warning，提示核对，因为号码可能是旧的或私人号；
- 结果性数字没有可核查来源——默认 warning，项目可用 `quality.number_level=block` 升级为阻断；
- 直接引语没有出处——同上，项目可用 `quality.quote_level` 控制。

「有来源」只认三种可核验形式：URL、`来源：`/`出处：`/`引自` 标注、`据…报告/统计/数据/公示` 的表述，
且必须与数字/引语落在同一段。不做语义判断，不猜「看起来像来源」。

规则命中一律带命中原文片段，避免只给一个「不通过」让人无从下手。
"""

from __future__ import annotations

import re

# 绝对化承诺：命中即阻断。顺序用于稳定输出。
ABSOLUTE_CLAIMS = [
    "包就业", "包分配", "保过", "保录取", "百分百", "100%", "稳赚", "零风险",
    "最权威", "最专业", "第一名", "绝对领先", "保证就业", "保证月薪", "月入过万",
]

NEGATION_WINDOW = 6
NEGATIONS = ("不", "非", "勿", "无", "避免", "杜绝", "禁止", "没有", "不以", "不得")

PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*[\w\u4e00-\u9fff-]+\s*\}\}")
PHONE_PATTERN = re.compile(r"1[3-9]\d{9}")
RESULT_NUMBER_PATTERN = re.compile(r"(就业率|月薪|薪资|平均薪资|起薪).{0,6}([0-9]+(?:\.[0-9]+)?[%元万千]?)")
QUOTE_PATTERN = re.compile(r"[“「]([^”」]{6,})[”」]")
SOURCE_PATTERN = re.compile(
    r"https?://|来源[:：]|出处[:：]|引自|数据来源|据.{0,24}(报告|统计|白皮书|数据|年报|公示|通报|问卷)"
)
SENTENCE_TYPES = ("result_number", "quote")


def _negated(body: str, start: int) -> bool:
    window = body[max(0, start - NEGATION_WINDOW):start]
    return any(word in window for word in NEGATIONS)


def _snippet(body: str, start: int, length: int) -> str:
    left = max(0, start - 12)
    right = min(len(body), start + length + 12)
    return body[left:right].replace("\n", " ").strip()


def _paragraph_bounds(body: str, position: int) -> tuple[int, int]:
    """数字/引语与来源必须同段：按空行或换行切段，取命中处所在段。"""
    start = body.rfind("\n", 0, position)
    start = 0 if start < 0 else start + 1
    end = body.find("\n", position)
    end = len(body) if end < 0 else end
    return start, end


def _has_source(body: str, position: int) -> bool:
    start, end = _paragraph_bounds(body, position)
    return bool(SOURCE_PATTERN.search(body[start:end]))


def run_quality_check(
    body: str,
    known_phones: set[str],
    *,
    number_level: str = "warn",
    quote_level: str = "warn",
) -> dict:
    blockers: list[dict] = []
    warnings: list[dict] = []

    for claim in ABSOLUTE_CLAIMS:
        for match in re.finditer(re.escape(claim), body):
            if _negated(body, match.start()):
                warnings.append({
                    "key": "claim_negated",
                    "label": "绝对化表述（否定语境）",
                    "detail": f"「{claim}」出现在否定表述里，未按违规处理：…{_snippet(body, match.start(), len(claim))}…",
                })
            else:
                blockers.append({
                    "key": "absolute_claim",
                    "label": "绝对化承诺",
                    "detail": f"命中「{claim}」：…{_snippet(body, match.start(), len(claim))}…",
                })

    placeholders = PLACEHOLDER_PATTERN.findall(body)
    if placeholders:
        blockers.append({
            "key": "placeholder",
            "label": "残留占位",
            "detail": "正文还有未填的槽位：" + "、".join(sorted(set(placeholders))),
        })

    for match in PHONE_PATTERN.finditer(body):
        number = match.group(0)
        if number not in known_phones:
            warnings.append({
                "key": "phone_unregistered",
                "label": "未登记号码",
                "detail": f"{number} 未在「对外渠道」登记过，确认是否为有效对外号码",
            })

    def _sink(level: str) -> list[dict]:
        return blockers if level == "block" else warnings

    for match in RESULT_NUMBER_PATTERN.finditer(body):
        if _has_source(body, match.start()):
            continue
        _sink(number_level).append({
            "key": "number_unsourced",
            "label": "结果性数字缺来源",
            "detail": f"「{match.group(0)}」所在段落没有 URL / 来源标注 / 数据出处，需给出可核查来源",
            "level": "block" if number_level == "block" else "warn",
        })

    for match in QUOTE_PATTERN.finditer(body):
        if _has_source(body, match.start()):
            continue
        _sink(quote_level).append({
            "key": "quote_unsourced",
            "label": "直接引语缺出处",
            "detail": f"引语「{_snippet(body, match.start(), len(match.group(0)))}」没有出处，需标来源单位或链接",
            "level": "block" if quote_level == "block" else "warn",
        })

    return {
        "ok": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "counts": {"blockers": len(blockers), "warnings": len(warnings)},
    }
