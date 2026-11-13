"""Track content review submission actor and time.

Revision ID: b72c8d9e0f11
Revises: a84f6e1b2c3d
"""

from alembic import op
import sqlalchemy as sa


revision = "b72c8d9e0f11"
down_revision = "a84f6e1b2c3d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("content_versions", sa.Column("submitted_by", sa.Uuid(), nullable=True))
    op.add_column("content_versions", sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_content_versions_submitted_by_users",
        "content_versions",
        "users",
        ["submitted_by"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_content_versions_submitted_by_users", "content_versions", type_="foreignkey")
    op.drop_column("content_versions", "submitted_at")
    op.drop_column("content_versions", "submitted_by")
