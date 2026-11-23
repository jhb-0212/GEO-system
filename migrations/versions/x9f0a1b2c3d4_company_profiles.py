"""企业档案 company_profiles

Revision ID: x9f0a1b2c3d4
Revises: v7d8e9f0a1b2
Create Date: 2026-11-23

对标加快科技「知识库 → 基础信息 / 企业智能体画像」，建项目级公司档案。
事实（地址/电话/资质/成立日期）仍以 facts 为准；本表只存对外表述与展示档案，
接口层做交叉校验，冲突需显式确认才写入。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "x9f0a1b2c3d4"
down_revision: Union[str, None] = "v7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "company_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("legal_name", sa.String(length=255), nullable=False),
        sa.Column("brand_name", sa.String(length=255), nullable=True),
        sa.Column("slogan", sa.String(length=255), nullable=True),
        sa.Column("province", sa.String(length=64), nullable=True),
        sa.Column("headcount", sa.Integer(), nullable=True),
        sa.Column("founded_on", sa.Date(), nullable=True),
        sa.Column("business_phone", sa.String(length=64), nullable=True),
        sa.Column("service_hotline", sa.String(length=64), nullable=True),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column(
            "stores", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "official_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "industries", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("regions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("products", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("highlights", sa.Text(), nullable=True),
        sa.Column("pain_points", sa.Text(), nullable=True),
        sa.Column("story", sa.Text(), nullable=True),
        sa.Column("founder_intro", sa.Text(), nullable=True),
        sa.Column("extra", sa.Text(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_company_profiles_project_id_projects",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_company_profiles_project"),
    )
    op.create_index(
        "ix_company_profiles_project_active",
        "company_profiles",
        ["project_id", "is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_company_profiles_project_active", table_name="company_profiles"
    )
    op.drop_table("company_profiles")
