"""P76 budget quote and receipt link

Revision ID: p76b1c2d3e4f5
Revises: d1e2f3a4b5c6
Create Date: 2026-11-20

把媒体投放预算绑到已批准报价，把发布回执逐条挂到预算。
两列都可空，现有开发工时预算与历史回执不回填。
"""

import sqlalchemy as sa
from alembic import op

revision = "p76b1c2d3e4f5"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 项目内复合外键需要 (project_id, id) 唯一键
    op.create_unique_constraint(
        "uq_media_quotes_project_id_id", "media_quotes", ["project_id", "id"]
    )
    op.create_unique_constraint(
        "uq_budget_approvals_project_id_id", "budget_approvals", ["project_id", "id"]
    )
    op.create_unique_constraint(
        "uq_publish_receipts_project_id_id", "publish_receipts", ["project_id", "id"]
    )

    op.add_column(
        "budget_approvals",
        sa.Column("media_quote_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_budget_approvals_media_quote", "budget_approvals", ["media_quote_id"]
    )
    op.create_foreign_key(
        "fk_budget_approvals_media_quote",
        "budget_approvals",
        "media_quotes",
        ["media_quote_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_budget_approvals_project_media_quote",
        "budget_approvals",
        "media_quotes",
        ["project_id", "media_quote_id"],
        ["project_id", "id"],
        ondelete="RESTRICT",
    )

    op.add_column(
        "publish_receipts",
        sa.Column("budget_approval_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_publish_receipts_budget", "publish_receipts", ["budget_approval_id"]
    )
    op.create_foreign_key(
        "fk_publish_receipts_budget",
        "publish_receipts",
        "budget_approvals",
        ["budget_approval_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_publish_receipts_project_budget",
        "publish_receipts",
        "budget_approvals",
        ["project_id", "budget_approval_id"],
        ["project_id", "id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_publish_receipts_project_budget", "publish_receipts", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_publish_receipts_budget", "publish_receipts", type_="foreignkey"
    )
    op.drop_index("ix_publish_receipts_budget", table_name="publish_receipts")
    op.drop_column("publish_receipts", "budget_approval_id")

    op.drop_constraint(
        "fk_budget_approvals_project_media_quote", "budget_approvals", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_budget_approvals_media_quote", "budget_approvals", type_="foreignkey"
    )
    op.drop_index("ix_budget_approvals_media_quote", table_name="budget_approvals")
    op.drop_column("budget_approvals", "media_quote_id")

    op.drop_constraint(
        "uq_publish_receipts_project_id_id", "publish_receipts", type_="unique"
    )
    op.drop_constraint(
        "uq_budget_approvals_project_id_id", "budget_approvals", type_="unique"
    )
    op.drop_constraint(
        "uq_media_quotes_project_id_id", "media_quotes", type_="unique"
    )
