"""企业档案：对外画像四套口径（company_profile_views）

Revision ID: t02c3d4e5f6a
Revises: s01b2c3d4e5f
Create Date: 2026-11-27

对标加快科技「知识库 → 企业智能体画像」：基础画像之外，再拆企业 / 招聘 / 会议 / 活动
四套说法。单独建表而不是塞进 company_profiles 的 JSONB，是为了四套口径能各自启停、
各自留 updated_at；可核验值仍然只认 facts，本表只存表达。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "t02c3d4e5f6a"
down_revision: Union[str, None] = "s01b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "company_profile_views",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=True),
        sa.Column("audience", sa.String(length=255), nullable=True),
        sa.Column("scenario_words", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("cautions", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_company_profile_views_project_id_projects",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_company_profile_views_project_kind",
        "company_profile_views",
        ["project_id", "kind"],
        unique=True,
    )
    op.create_index(
        "ix_company_profile_views_project_active",
        "company_profile_views",
        ["project_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_index("ix_company_profile_views_project_active", table_name="company_profile_views")
    op.drop_index("uq_company_profile_views_project_kind", table_name="company_profile_views")
    op.drop_table("company_profile_views")
