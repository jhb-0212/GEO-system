"""K8 微站：site_sites + site_modules

Revision ID: c8d9e0f1a2b3
Revises: a6b7c8d9e0f1
Create Date: 2026-11-23

一个项目一个站；站内 6 个模块（home/services/news/download/poster/card）各一条。
未发布的站公开接口一律 404。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, None] = "a6b7c8d9e0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "site_sites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("intro", sa.Text(), nullable=True),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_site_sites_project_id_projects", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_site_sites_project_id"),
        sa.UniqueConstraint("slug", name="uq_site_sites_slug"),
    )

    op.create_table(
        "site_modules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("module_type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column(
            "content", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_site_modules_project_id_projects", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["site_sites.id"], name="fk_site_modules_site_id_site_sites", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "module_type", name="uq_site_modules_site_type"),
        sa.CheckConstraint(
            "module_type in ('home','services','news','download','poster','card')",
            name="ck_site_modules_type",
        ),
    )
    op.create_index("ix_site_modules_project_order", "site_modules", ["project_id", "sort_order"])


def downgrade() -> None:
    op.drop_index("ix_site_modules_project_order", table_name="site_modules")
    op.drop_table("site_modules")
    op.drop_table("site_sites")
