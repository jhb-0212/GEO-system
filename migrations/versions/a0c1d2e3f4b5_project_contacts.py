"""对外渠道台账：project_contacts

Revision ID: a0c1d2e3f4b5
Revises: z9b8c7d6e5f4
Create Date: 2026-11-23

对标加快科技「基础信息 → 联系方式」：把公众号、小红书、抖音、门店电话等多渠道
露面方式放在一张表里，各自标注对外公开还是内部使用。
渠道用代码常量而非原生枚举，新增渠道不必再跑迁移。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a0c1d2e3f4b5"
down_revision: Union[str, None] = "z9b8c7d6e5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_contacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_project_contacts_project_id_projects", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_project_contacts_created_by_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "channel", "value", name="uq_project_contacts_project_channel_value"),
    )
    op.create_index("ix_project_contacts_project_channel", "project_contacts", ["project_id", "channel"])


def downgrade() -> None:
    op.drop_index("ix_project_contacts_project_channel", table_name="project_contacts")
    op.drop_table("project_contacts")
