"""Revision ID: n0d1e2f3a4b5
Revises: m9c0e1f2a3b4
Create Date: 2026-11-24

媒体资源矩阵的平台级目录配置：一份 JSON 目录，多个客户、多个项目共用。
不挂 project_id，避免把展示目录变成某个客户的项目数据。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "n0d1e2f3a4b5"
down_revision = "m9c0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_matrix_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", name="uq_media_matrix_configs_key"),
    )


def downgrade() -> None:
    op.drop_table("media_matrix_configs")
