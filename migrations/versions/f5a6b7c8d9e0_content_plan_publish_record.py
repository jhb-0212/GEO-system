"""B7 新媒体发布记录：content_plans 加 is_published / publish_url / published_at / play_note

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-11-23

只记「是否已发布 + 发布链接 + 人工备注」，不存播放/互动数值明细，
播放数据由运营写在 play_note 里（取舍清单 B7 的拒绝项）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, None] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "content_plans",
        sa.Column(
            "is_published", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column("content_plans", sa.Column("publish_url", sa.String(length=500), nullable=True))
    op.add_column(
        "content_plans", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("content_plans", sa.Column("play_note", sa.Text(), nullable=True))
    # 扩容「已发布」列表：计划页按项目 + 是否发布过滤
    op.create_index(
        "ix_content_plans_project_published",
        "content_plans",
        ["project_id", "is_published"],
    )


def downgrade() -> None:
    op.drop_index("ix_content_plans_project_published", table_name="content_plans")
    op.drop_column("content_plans", "play_note")
    op.drop_column("content_plans", "published_at")
    op.drop_column("content_plans", "publish_url")
    op.drop_column("content_plans", "is_published")
