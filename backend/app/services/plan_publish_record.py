"""B7 新媒体发布记录：只落「是否已发布 + 发布链接 + 人工备注」。

口径来自取舍清单 B7：
- 吸收：计划表能直接看到「已发布 / 链接」，不必再翻发布任务；
- 拒绝：不自动采集播放/互动数据，不做趋势图，数值只由运营手填备注。
因此这里只做两件事：字段互斥校验、状态翻转时维护 published_at。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.errors import BusinessValidationError

_URL_PREFIXES = ("http://", "https://")


def validate_publish_record(
    *, is_published: bool | None, publish_url: str | None
) -> str | None:
    """返回规范化后的链接（无链接时为 None），不合法直接抛 422。

    两条硬约束（互相咬合，避免出现「说发了但没链接」或「没发却挂链接」）：
    - is_published=True 必须带链接；
    - 带链接必须 is_published=True。
    """
    url = (publish_url or "").strip()
    if is_published and not url:
        raise BusinessValidationError(
            "标记为已发布时必须填写发布链接", code="publish_url_required"
        )
    if url and not is_published:
        raise BusinessValidationError(
            "填写发布链接前请先把计划标记为已发布", code="publish_url_without_published"
        )
    if url:
        if not url.startswith(_URL_PREFIXES) or any(ch.isspace() for ch in url):
            raise BusinessValidationError(
                "发布链接必须是 http(s) 开头且不含空格的地址", code="publish_url_invalid"
            )
    return url or None


def apply_publish_record(
    plan: Any, *, is_published: bool | None, publish_url: str | None, now: datetime | None = None
) -> None:
    """把通过校验的发布记录写到计划上，并维护 published_at。

    published_at 只在首次置为已发布时写入；撤回发布时一并清空，
    这样「已发布时间」永远指向当前这条链接，不会留下历史残值。
    """
    stamp = now or datetime.now(UTC)
    url = validate_publish_record(is_published=is_published, publish_url=publish_url)
    if is_published:
        plan.is_published = True
        plan.publish_url = url
        if plan.published_at is None:
            plan.published_at = stamp
    else:
        plan.is_published = False
        plan.publish_url = None
        plan.published_at = None
