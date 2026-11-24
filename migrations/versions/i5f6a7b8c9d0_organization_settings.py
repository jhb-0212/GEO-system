"""Revision ID: i5f6a7b8c9d0
Revises: h4e5f6a7b8c9
Create Date: 2026-11-24

客户级设置：inherit_members / quotas / strategy。默认空对象 = 不继承、不限配额、无客户策略。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "i5f6a7b8c9d0"
down_revision = "h4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("settings", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("organizations", "settings")
