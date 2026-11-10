"""统一响应封装：所有成功响应都是 {"data": ...}，与错误信封 {"error": ...} 对称。"""

from typing import Any


def ok(payload: Any) -> dict[str, Any]:
    return {"data": payload}
