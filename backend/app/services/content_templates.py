"""内容模板：解析槽位与渲染正文。

槽位规则：`{{名称}}`，名称允许中文、字母、数字、下划线；重复出现算同一个槽位。
渲染时任何一个槽位缺值都直接报错，不用空串凑出一篇「看起来完整」的稿子。
"""

from __future__ import annotations

import re

SLOT_PATTERN = re.compile(r"\{\{\s*([\w\u4e00-\u9fff-]+)\s*\}\}")


def extract_slots(skeleton: str) -> list[dict]:
    """从骨架解析槽位；按出现顺序去重，全部标记为必填。"""
    seen: list[str] = []
    for match in SLOT_PATTERN.finditer(skeleton):
        key = match.group(1)
        if key not in seen:
            seen.append(key)
    return [{"key": key, "label": key, "required": True} for key in seen]


def render(skeleton: str, values: dict[str, str]) -> str:
    """按槽位渲染；缺值抛 ValueError，调用方据此返回 400。"""
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = (values.get(key) or "").strip()
        if not value:
            missing.append(key)
            return match.group(0)
        return value

    rendered = SLOT_PATTERN.sub(replace, skeleton)
    if missing:
        raise ValueError("槽位缺值：" + "、".join(sorted(set(missing))))
    return rendered
