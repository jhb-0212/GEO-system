"""G1/G2 生成批次：缺口 → 草稿 → 审稿 → 导出。

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-11-23

两张表：批次（计数与状态）+ 生成项（简报/草稿/审稿标记）。
批次项必须有来源：question_id 或 opportunity_id 至少一个非空。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "generation_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("engine_code", sa.String(length=64), nullable=True),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("drafted_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_generation_batches_project_id_projects", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_generation_batches_created_by_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("source in ('opportunity','question')", name="ck_generation_batches_source"),
        sa.CheckConstraint(
            "status in ('queued','running','completed','failed')",
            name="ck_generation_batches_status",
        ),
    )
    op.create_index(
        "ix_generation_batches_project_created",
        "generation_batches",
        ["project_id", "created_at"],
    )

    op.create_table(
        "generation_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=True),
        sa.Column("opportunity_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column(
            "brief", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("generation_mode", sa.String(length=16), nullable=False, server_default="template"),
        sa.Column("draft_body", sa.Text(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reviewed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_generation_items_project_id_projects", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["generation_batches.id"], name="fk_generation_items_batch_id_generation_batches", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["question_id"], ["questions.id"], name="fk_generation_items_question_id_questions", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], ["opportunities.id"], name="fk_generation_items_opportunity_id_opportunities", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status in ('pending','drafted','failed')",
            name="ck_generation_items_status",
        ),
        sa.CheckConstraint(
            "generation_mode in ('template','model')",
            name="ck_generation_items_mode",
        ),
    )
    op.create_index(
        "ix_generation_items_batch_order", "generation_items", ["batch_id", "sort_order"]
    )
    op.create_index(
        "ix_generation_items_project_status", "generation_items", ["project_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_generation_items_project_status", table_name="generation_items")
    op.drop_index("ix_generation_items_batch_order", table_name="generation_items")
    op.drop_table("generation_items")
    op.drop_index("ix_generation_batches_project_created", table_name="generation_batches")
    op.drop_table("generation_batches")
