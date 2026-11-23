"""内容工厂模板：content_templates

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-11-23

模板只沉淀骨架与槽位（{{槽位}}），生成结果仍是普通 draft 内容，
必须继续走审核流程。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "content_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("channel_category", sa.String(length=32), nullable=True),
        sa.Column("question_type", sa.String(length=16), nullable=True),
        sa.Column("skeleton", sa.Text(), nullable=False),
        sa.Column("slots", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_content_templates_project_id_projects", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_content_templates_created_by_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_content_templates_project_active", "content_templates", ["project_id", "is_active"])


def downgrade() -> None:
    op.drop_index("ix_content_templates_project_active", table_name="content_templates")
    op.drop_table("content_templates")
