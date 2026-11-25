"""给内容条目增加可选内容形式。

GEO 的六类内容形式只在创建母稿时标注；历史内容保持 NULL，不做回填，
避免把旧文章按标题猜测成某种形式。

Revision ID: s2b3c4d5e6f7
Revises: r1a2b3c4d5e6
Create Date: 2026-11-25
"""

from alembic import op
import sqlalchemy as sa

revision = "s2b3c4d5e6f7"
down_revision = "r1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_items",
        sa.Column("content_type", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("content_items", "content_type")
