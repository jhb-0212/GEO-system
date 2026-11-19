"""月度报告快照：同一项目同月一份不可变报告副本。

Revision ID: b7c8d9e0f1a2
Revises: x7b8c9d0e1f2
Create Date: 2026-11-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b7c8d9e0f1a2"
down_revision = "x7b8c9d0e1f2"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "monthly_report_snapshots" in _tables():
        return
    op.create_table(
        "monthly_report_snapshots",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_by", sa.Uuid()),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "definitions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("rule_version", sa.String(length=32), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["captured_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "month",
            name="uq_monthly_report_snapshots_project_month",
        ),
    )
    op.create_index(
        "ix_monthly_report_snapshots_project_captured_at",
        "monthly_report_snapshots",
        ["project_id", "captured_at"],
    )


def downgrade() -> None:
    if "monthly_report_snapshots" in _tables():
        op.drop_table("monthly_report_snapshots")
