"""fixed-period monitoring retest plans

Revision ID: r98d3e4f5a6b
Revises: q87c2d3e4f6a
Create Date: 2026-11-21

固定周期复测：计划表负责周期与下一次执行时间；轮次记录计划槽位，
唯一约束 (retest_plan_id, scheduled_for) 防止 beat 重跑建出重复轮次。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "r98d3e4f5a6b"
down_revision = "q87c2d3e4f6a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monitoring_retest_plans",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("interval_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("first_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "entry_scope",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[\"api\", \"app_search\"]'::jsonb"),
        ),
        sa.Column("samples_per_cell", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_monitoring_retest_plans_project_id_projects",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_monitoring_retest_plans_created_by_users",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "project_id", "name", name="uq_monitoring_retest_plans_project_name"
        ),
    )
    op.create_index(
        "ix_monitoring_retest_plans_due",
        "monitoring_retest_plans",
        ["next_run_at", "enabled"],
    )
    op.create_index(
        "ix_monitoring_retest_plans_project",
        "monitoring_retest_plans",
        ["project_id"],
    )

    op.add_column(
        "monitoring_rounds",
        sa.Column("retest_plan_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.add_column(
        "monitoring_rounds",
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_monitoring_rounds_retest_plan_id_monitoring_retest_plans",
        "monitoring_rounds",
        "monitoring_retest_plans",
        ["retest_plan_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_monitoring_rounds_plan_slot",
        "monitoring_rounds",
        ["retest_plan_id", "scheduled_for"],
    )
    op.create_index(
        "ix_monitoring_rounds_retest_plan",
        "monitoring_rounds",
        ["retest_plan_id", "scheduled_for"],
    )


def downgrade() -> None:
    op.drop_index("ix_monitoring_rounds_retest_plan", table_name="monitoring_rounds")
    op.drop_constraint(
        "uq_monitoring_rounds_plan_slot", "monitoring_rounds", type_="unique"
    )
    op.drop_constraint(
        "fk_monitoring_rounds_retest_plan_id_monitoring_retest_plans", "monitoring_rounds", type_="foreignkey"
    )
    op.drop_column("monitoring_rounds", "scheduled_for")
    op.drop_column("monitoring_rounds", "retest_plan_id")

    op.drop_index(
        "ix_monitoring_retest_plans_project", table_name="monitoring_retest_plans"
    )
    op.drop_index(
        "ix_monitoring_retest_plans_due", table_name="monitoring_retest_plans"
    )
    op.drop_table("monitoring_retest_plans")
