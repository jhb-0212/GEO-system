"""add sample sampling context

Revision ID: r1a2b3c4d5e6
Revises: q3d4e5f6a7b8
Create Date: 2026-11-24

手测样本新增端上下文：手机 App 与网页端即使同一模型，设备、App 版本、登录态
和个性化开关也会造成不同回答。入口类型仍由任务关联的引擎入口决定；这一列只
记录采样时的事实，不参与命中判定。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "r1a2b3c4d5e6"
down_revision = "q3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "monitoring_samples",
        sa.Column(
            "sampling_context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("monitoring_samples", "sampling_context")
