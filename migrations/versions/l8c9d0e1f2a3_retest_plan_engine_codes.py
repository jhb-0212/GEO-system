"""Revision ID: l8c9d0e1f2a3
Revises: k7b8c9d0e1f2
Create Date: 2026-11-24

复测计划增加 engine_codes：只影响该计划的 API 引擎范围，空数组表示全部启用引擎。
"""

from alembic import op

revision = "l8c9d0e1f2a3"
down_revision = "k7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE monitoring_retest_plans
        ADD COLUMN IF NOT EXISTS engine_codes jsonb NOT NULL DEFAULT '[]'::jsonb;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE monitoring_retest_plans
        DROP COLUMN IF EXISTS engine_codes;
        """
    )
