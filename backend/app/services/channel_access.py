"""渠道准入门禁：未通过准入审批的渠道不能进入发布与引用归属链。

`approval_status` 与业务四态正交：待审核 / 已驳回渠道既不能建发布任务、
登记发布账号，也不能在引用复核中被挂接为归属渠道。存在性与项目归属由
调用方的 `require_scoped_row` / 查询条件负责，这里只断言准入状态。
"""

from app.core.errors import AppError
from app.models import Channel
from app.models.enums import ChannelApprovalStatus


def ensure_channel_approved(channel: Channel) -> None:
    """渠道已准入才可发布或挂接引用；否则抛 `channel_not_approved`。"""
    if channel.approval_status != ChannelApprovalStatus.APPROVED:
        raise AppError(
            "渠道尚未通过准入审批，不能发布或挂接引用回执",
            code="channel_not_approved",
        )
