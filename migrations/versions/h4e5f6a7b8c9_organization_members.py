"""Revision ID: h4e5f6a7b8c9
Revises: g3d4e5f6a7b8
Create Date: 2026-11-24

客户级通讯录：organization_members。本身不授予项目访问权；
同步到项目是显式动作，只加 viewer，避免客户名册自动扩权。
"""

import sqlalchemy as sa
from alembic import op

revision = "h4e5f6a7b8c9"
down_revision = "g3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=32), server_default="member", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_organization_members_user"),
    )
    op.create_index("ix_organization_members_org", "organization_members", ["organization_id", "is_active"])


def downgrade() -> None:
    op.drop_index("ix_organization_members_org", table_name="organization_members")
    op.drop_table("organization_members")
