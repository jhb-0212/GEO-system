"""内容状态联动：版本状态迁移与当前条目同步集中在这里。

内容六态里 draft / pending_review / approved / rejected 由审核流程驱动；
scheduled / published / needs_attention 由发布链路驱动。所有写点都走
`ensure_content_transition`，不允许在接口里直接赋值绕过状态机。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import ContentItem, ContentVersion
from app.models.enums import ContentStatus
from app.services.state_machine import ensure_content_transition


def sync_current_item_status(item: ContentItem, version: ContentVersion) -> None:
    """条目状态只跟随当前版本；历史版本不得污染条目状态。"""
    if item.current_version_id != version.id:
        return
    if item.status != version.status:
        item.status = version.status


def mark_version_status(
    db: Session,
    version: ContentVersion,
    target: ContentStatus,
) -> ContentStatus:
    """迁移版本状态并同步当前条目；非法迁移抛 ReviewStateError。"""
    version.status = ensure_content_transition(version.status, target)
    item = db.get(ContentItem, version.item_id)
    if item is not None:
        sync_current_item_status(item, version)
    return version.status
