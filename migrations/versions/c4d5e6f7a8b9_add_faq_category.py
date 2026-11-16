"""add faq category

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f6a7
Create Date: 2026-11-16 20:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("faqs", sa.Column("category", sa.String(length=64), nullable=True))
    op.create_index("ix_faqs_project_category", "faqs", ["project_id", "category"])


def downgrade() -> None:
    op.drop_index("ix_faqs_project_category", table_name="faqs")
    op.drop_column("faqs", "category")
