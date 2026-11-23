"""Revision ID: df8a9b0c1d2e
Revises: ce7f8a9b0c1d
Create Date: 2026-11-24
"""

from alembic import op
import sqlalchemy as sa

revision = "df8a9b0c1d2e"
down_revision = "ce7f8a9b0c1d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "engine_targets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("content_plan_id", sa.Uuid()),
        sa.Column("engine_id", sa.Uuid(), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="1", nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("source", sa.String(length=20), server_default="manual", nullable=False),
        sa.Column("created_by", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["content_plan_id"], ["content_plans.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["engine_id"], ["ai_engines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "channel_id", "engine_id", name="uq_engine_targets_project_channel_engine"),
    )
    op.create_index("ix_engine_targets_project_channel", "engine_targets", ["project_id", "channel_id"])


def downgrade() -> None:
    op.drop_index("ix_engine_targets_project_channel", table_name="engine_targets")
    op.drop_table("engine_targets")
