"""CSV 单元格安全：导出内容不能把用户字段解释成公式。

Excel / WPS 会把以 `= + - @` 开头的单元格当公式；这里在写 CSV 前加文本前导符。
正常负数（`-12.5`、`+3` 这类纯数值）保持数值形态，不把所有负数都转成文本。
"""

from __future__ import annotations

import re
from typing import Any

_NUMERIC = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def safe_csv_cell(value: Any) -> Any:
    """返回可安全写入 CSV 的值；非字符串原样返回。"""
    if not isinstance(value, str):
        return value
    if not value:
        return value
    stripped = value.lstrip()
    if not stripped or stripped[0] not in _FORMULA_PREFIXES:
        return value
    if stripped[0] in "+-" and _NUMERIC.fullmatch(stripped):
        return value
    return "'" + value


def safe_csv_row(values: list[Any]) -> list[Any]:
    return [safe_csv_cell(value) for value in values]
