"""B5 体检引擎：health_check_runs + health_check_items

Revision ID: e0f1a2b3c4d5
Revises: c8d9e0f1a2b3
Create Date: 2026-11-23

一次体检一份快照（runs），逐项结论存 items；不存总分，故没有 score 列。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e0f1a2b3c4d5"
down_revision: Union[str, None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "health_check_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("ruleset_version", sa.String(length=16), nullable=False),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unknown_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("triggered_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_health_check_runs_project_id_projects", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["triggered_by"], ["users.id"], name="fk_health_check_runs_triggered_by_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_health_check_runs_project_created",
        "health_check_runs",
        ["project_id", "created_at"],
    )

    op.create_table(
        "health_check_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("check_key", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("numerator", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("denominator", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unit", sa.String(length=8), nullable=False, server_default="条"),
        sa.Column("target_percent", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("hint", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_health_check_items_project_id_projects", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["health_check_runs.id"], name="fk_health_check_items_run_id_health_check_runs", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status in ('pass','fail','unknown')",
            name="ck_health_check_items_status",
        ),
    )
    op.create_index(
        "ix_health_check_items_run_order", "health_check_items", ["run_id", "sort_order"]
    )


def downgrade() -> None:
    op.drop_index("ix_health_check_items_run_order", table_name="health_check_items")
    op.drop_table("health_check_items")
    op.drop_index("ix_health_check_runs_project_created", table_name="health_check_runs")
    op.drop_table("health_check_runs")
