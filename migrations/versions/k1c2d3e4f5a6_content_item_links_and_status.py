"""content item link invariant and status backfill

- 渠道稿必须有母稿和渠道；母稿不能反向挂 parent/channel。
- 已有归档渠道稿允许保持历史原样（当前库确实存在一条归档孤儿稿）。
- 同时把 content_items.status 回填为当前版本状态，消除 item/version 双事实源。

Revision ID: k1c2d3e4f5a6
Revises: j0b1c2d3e4f5
Create Date: 2026-11-17 20:30:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "k1c2d3e4f5a6"
down_revision: Union[str, None] = "j0b1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LINK_CHECK = (
    "(kind = 'master' AND parent_id IS NULL AND channel_id IS NULL) OR "
    "(kind = 'channel' AND (status = 'archived' OR "
    "(parent_id IS NOT NULL AND channel_id IS NOT NULL)))"
)


def upgrade() -> None:
    # 回填当前版本状态；归档条目保持 archived，不被历史版本覆盖。
    op.execute(
        "UPDATE content_items AS i "
        "SET status = v.status "
        "FROM content_versions AS v "
        "WHERE i.current_version_id = v.id "
        "AND i.status <> 'archived' "
        "AND i.status <> v.status"
    )
    op.create_check_constraint("content_links", "content_items", LINK_CHECK)


def downgrade() -> None:
    op.drop_constraint("content_links", "content_items", type_="check")
