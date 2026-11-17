"""add faq soft delete markers

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-11-17 09:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "d6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("faqs", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("faqs", sa.Column("deleted_by", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_faqs_deleted_by_users",
        "faqs",
        "users",
        ["deleted_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_faqs_project_deleted", "faqs", ["project_id", "deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_faqs_project_deleted", table_name="faqs")
    op.drop_constraint("fk_faqs_deleted_by_users", "faqs", type_="foreignkey")
    op.drop_column("faqs", "deleted_by")
    op.drop_column("faqs", "deleted_at")
