"""文本摘要：把长回答压成可展示的一段，完整文本仍留在样本表里。

以前 channels / citations / monitoring 各写一份，长度（200 / 160 / 200）和截断后缀
（带不带省略号）都各自藏了默认值，同一段回答在两个页面截出不同结果。
这里把「截多长」「要不要省略号」变成显式参数，调用方自己声明口径。
"""

from __future__ import annotations


def excerpt(value: str | None, limit: int = 200, *, ellipsis: bool = True) -> str | None:
    """折叠空白并按字符数截断。

    `ellipsis=False` 保留旧引用列表的行为（硬截断、不加省略号），避免改变既有响应。
    """
    if not value:
        return None
    text = " ".join(value.split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..." if ellipsis else text[:limit]
