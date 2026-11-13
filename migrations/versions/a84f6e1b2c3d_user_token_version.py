"""Add version to invalidate previously issued user access tokens.

Revision ID: a84f6e1b2c3d
Revises: 13d970f42b3c
"""

from alembic import op
import sqlalchemy as sa


revision = "a84f6e1b2c3d"
down_revision = "13d970f42b3c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
