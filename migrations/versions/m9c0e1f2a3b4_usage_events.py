"""Revision ID: m9c0e1f2a3b4
Revises: l8c9d0e1f2a3
Create Date: 2026-11-24

消耗计量账本：append-only，只记用量不记价格。
唯一键 (project_id, metric, source_type, source_id) 保证同一业务事实重跑不重复计数。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "m9c0e1f2a3b4"
down_revision = "l8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Integer(), server_default="1", nullable=False),
        sa.Column("source_type", sa.String(length=48), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "metric", "source_type", "source_id",
            name="uq_usage_events_project_metric_source",
        ),
    )
    op.create_index("ix_usage_events_project_day", "usage_events", ["project_id", "occurred_on"])
    op.create_index(
        "ix_usage_events_org_metric_day", "usage_events", ["organization_id", "metric", "occurred_on"]
    )


def downgrade() -> None:
    op.drop_index("ix_usage_events_org_metric_day", table_name="usage_events")
    op.drop_index("ix_usage_events_project_day", table_name="usage_events")
    op.drop_table("usage_events")
