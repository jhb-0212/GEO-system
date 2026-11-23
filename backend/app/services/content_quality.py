"""内容提交前质检：在进审核队列之前把「必然被打回」的问题挡住。

只做能给出定位与依据的规则：
- 绝对化承诺（包就业/保过/100%…）——命中即 blocker，除非前文是否定表述；
- 残留模板占位 `{{槽位}}`——blocker，说明正文没填完就提交；
- 正文里的手机号没在「对外渠道」登记——warning，提示核对，因为号码可能是旧的或私人号；
- 正文出现「就业率/月薪」等结果性数字——warning，提示附来源，不冒充判定。

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


def _negated(body: str, start: int) -> bool:
    window = body[max(0, start - NEGATION_WINDOW):start]
    return any(word in window for word in NEGATIONS)


def _snippet(body: str, start: int, length: int) -> str:
    left = max(0, start - 12)
    right = min(len(body), start + length + 12)
    return body[left:right].replace("\n", " ").strip()


def run_quality_check(body: str, known_phones: set[str]) -> dict:
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

    for match in RESULT_NUMBER_PATTERN.finditer(body):
        warnings.append({
            "key": "result_number",
            "label": "结果性数字",
            "detail": f"「{match.group(0)}」属结果性表述，需在正文或附件给出可核查来源",
        })

    return {
        "ok": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "counts": {"blockers": len(blockers), "warnings": len(warnings)},
    }
