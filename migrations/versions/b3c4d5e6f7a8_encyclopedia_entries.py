"""K4 百科词条：起草 → 审核 → 外链登记。

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-11-23

一张表：词条本体 + 审核痕迹 + 外链。平台与状态用 CHECK 约束限值，
同项目内 slug 唯一（词条名改字不重复登记）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "encyclopedia_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "references", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reviewer_id", sa.Uuid(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_url", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_encyclopedia_entries_project_id_projects", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"], ["users.id"], name="fk_encyclopedia_entries_reviewer_id_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "slug", name="uq_encyclopedia_entries_project_slug"),
        sa.CheckConstraint(
            "platform in ('baidu_baike','sogou_baike','douyin_baike','wikipedia','other')",
            name="ck_encyclopedia_entries_platform",
        ),
        sa.CheckConstraint(
            "status in ('draft','pending_review','published','rejected')",
            name="ck_encyclopedia_entries_status",
        ),
    )
    op.create_index(
        "ix_encyclopedia_entries_project_status",
        "encyclopedia_entries",
        ["project_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_encyclopedia_entries_project_status", table_name="encyclopedia_entries")
    op.drop_table("encyclopedia_entries")
