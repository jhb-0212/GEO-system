"""渠道改编血缘：content_derivations

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-11-23

只记「母稿版本 + 来源哈希 + 渠道」，渠道稿正文仍在 content_versions；
母稿再改后来源哈希与母稿当前哈希不一致即视为未跟版。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "content_derivations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("master_item_id", sa.Uuid(), nullable=False),
        sa.Column("channel_item_id", sa.Uuid(), nullable=False),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("source_version_id", sa.Uuid(), nullable=False),
        sa.Column("source_content_hash", sa.String(length=64), nullable=False),
        sa.Column("checks", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("synced_at", sa.String(length=32), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_content_derivations_project_id_projects", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["master_item_id"], ["content_items.id"], name="fk_content_derivations_master_item_id_content_items", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_item_id"], ["content_items.id"], name="fk_content_derivations_channel_item_id_content_items", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], name="fk_content_derivations_channel_id_channels", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_version_id"], ["content_versions.id"], name="fk_content_derivations_source_version_id_content_versions", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_content_derivations_created_by_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "channel_item_id", name="uq_content_derivations_channel_item"),
    )
    op.create_index("ix_content_derivations_project_master", "content_derivations", ["project_id", "master_item_id"])


def downgrade() -> None:
    op.drop_index("ix_content_derivations_project_master", table_name="content_derivations")
    op.drop_table("content_derivations")
