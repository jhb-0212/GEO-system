"""机会中心：证据驱动的运营任务与六因子评分

Revision ID: z8e9f0a1b2c3
Revises: y7e8f9a0b1c2
Create Date: 2026-11-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "z8e9f0a1b2c3"
down_revision: Union[str, None] = "y7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "opportunities",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column(
            "gap_type",
            sa.Enum(
                "own_page",
                "media_report",
                "reference_site",
                "ugc",
                "fact_correction",
                "website_fix",
                name="opportunity_gap_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("question_id", sa.Uuid(), nullable=True),
        sa.Column("sample_id", sa.Uuid(), nullable=True),
        sa.Column("evidence_refs", postgresql.JSONB(), nullable=False),
        sa.Column("score_factors", postgresql.JSONB(), nullable=False),
        sa.Column("score_weights", postgresql.JSONB(), nullable=False),
        sa.Column("priority_score", sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "in_progress",
                "done",
                "dismissed",
                name="opportunity_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="open",
            nullable=False,
        ),
        sa.Column("linked_content_plan_id", sa.Uuid(), nullable=True),
        sa.Column("linked_content_item_id", sa.Uuid(), nullable=True),
        sa.Column("linked_publish_task_id", sa.Uuid(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["linked_content_item_id"],
            ["content_items.id"],
            name=op.f("fk_opportunities_linked_content_item_id_content_items"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["linked_content_plan_id"],
            ["content_plans.id"],
            name=op.f("fk_opportunities_linked_content_plan_id_content_plans"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["linked_publish_task_id"],
            ["publish_tasks.id"],
            name=op.f("fk_opportunities_linked_publish_task_id_publish_tasks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_opportunities_owner_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_opportunities_project_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["questions.id"],
            name=op.f("fk_opportunities_question_id_questions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["sample_id"],
            ["monitoring_samples.id"],
            name=op.f("fk_opportunities_sample_id_monitoring_samples"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_opportunities")),
    )
    op.create_index(
        "ix_opportunities_project_status_score",
        "opportunities",
        ["project_id", "status", "priority_score"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_opportunities_project_status_score", table_name="opportunities")
    op.drop_table("opportunities")
