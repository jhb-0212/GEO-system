"""Revision ID: j6a7b8c9d0e1
Revises: i5f6a7b8c9d0
Create Date: 2026-11-24

客户用量按天快照：趋势以快照事实为准；历史缺失日期仍可按创建时间回算兜底。
"""

import sqlalchemy as sa
from alembic import op

revision = "j6a7b8c9d0e1"
down_revision = "i5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization_usage_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("captured_on", sa.Date(), nullable=False),
        sa.Column("projects", sa.Integer(), server_default="0", nullable=False),
        sa.Column("members", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "captured_on", name="uq_organization_usage_snapshots_day"),
    )
    op.create_index(
        "ix_organization_usage_snapshots_org_day",
        "organization_usage_snapshots",
        ["organization_id", "captured_on"],
    )


def downgrade() -> None:
    op.drop_index("ix_organization_usage_snapshots_org_day", table_name="organization_usage_snapshots")
    op.drop_table("organization_usage_snapshots")
