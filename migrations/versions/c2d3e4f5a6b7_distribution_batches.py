"""投喂批次：distribution_batches / distribution_batch_items

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-11-23

批次只引用 content_version，不复制正文；预检结果以 JSONB 落库，
状态用 VARCHAR + CHECK（与项目其余 str_enum 一致）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "distribution_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="blocked"),
        sa.Column("target_engines", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("precheck", postgresql.JSONB(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatched_by", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('blocked', 'ready', 'dispatched')",
            name="distribution_batch_status",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_distribution_batches_project_id_projects", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["dispatched_by"], ["users.id"], name="fk_distribution_batches_dispatched_by_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_distribution_batches_created_by_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_distribution_batches_project_status", "distribution_batches", ["project_id", "status"])

    op.create_table(
        "distribution_batch_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("content_version_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_distribution_batch_items_project_id_projects", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["batch_id"], ["distribution_batches.id"], name="fk_distribution_batch_items_batch_id_distribution_batches", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["content_version_id"], ["content_versions.id"], name="fk_distribution_batch_items_version", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("distribution_batch_items")
    op.drop_index("ix_distribution_batches_project_status", table_name="distribution_batches")
    op.drop_table("distribution_batches")
