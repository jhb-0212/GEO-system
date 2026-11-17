"""business confirmation, priority and four-category budget approvals

Revision ID: m4f5a6b7c8d9
Revises: l2d3e4f5a6b7
Create Date: 2026-11-18 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "m4f5a6b7c8d9"
down_revision: Union[str, None] = "l2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 项目资料确认：优先级与确认时间 / 确认人；priority 1 最高、5 最低。
    op.add_column(
        "projects",
        sa.Column("priority", sa.Integer(), server_default="3", nullable=False),
    )
    op.add_column(
        "projects",
        sa.Column("business_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("business_confirmed_by", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_check_constraint(
        "priority_range",
        "projects",
        "priority BETWEEN 1 AND 5",
    )
    op.create_foreign_key(
        "fk_projects_business_confirmed_by_users",
        "projects",
        "users",
        ["business_confirmed_by"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "budget_approvals",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="CNY"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("requested_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("approved_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "category IN ('development_hours', 'content_production', 'media_placement', 'monitoring_service')",
            name="budget_category",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="budget_approval_status",
        ),
        sa.CheckConstraint("amount > 0", name="amount_positive"),
        sa.CheckConstraint(
            "quantity IS NULL OR quantity > 0",
            name="quantity_positive",
        ),
        sa.CheckConstraint(
            "unit_price IS NULL OR unit_price >= 0",
            name="unit_price_nonnegative",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_budget_approvals_project_status_category",
        "budget_approvals",
        ["project_id", "status", "category"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_budget_approvals_project_status_category",
        table_name="budget_approvals",
    )
    op.drop_table("budget_approvals")
    op.drop_constraint(
        "fk_projects_business_confirmed_by_users", "projects", type_="foreignkey"
    )
    op.drop_constraint("ck_projects_priority_range", "projects", type_="check")
    op.drop_column("projects", "business_confirmed_by")
    op.drop_column("projects", "business_confirmed_at")
    op.drop_column("projects", "priority")
