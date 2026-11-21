"""citation source evidence fields

Revision ID: q87c2d3e4f6a
Revises: p76b1c2d3e4f5
Create Date: 2026-11-20

把 provider 的站点名、摘要/片段和发布时间归一化到 monitoring_citations，
避免信源排行只能到 URL/域名级。三列均可空，历史引用不回填。
"""

import sqlalchemy as sa
from alembic import op

revision = "q87c2d3e4f6a"
down_revision = "p76b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "monitoring_citations",
        sa.Column("site_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "monitoring_citations",
        sa.Column("snippet", sa.Text(), nullable=True),
    )
    op.add_column(
        "monitoring_citations",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("monitoring_citations", "published_at")
    op.drop_column("monitoring_citations", "snippet")
    op.drop_column("monitoring_citations", "site_name")
