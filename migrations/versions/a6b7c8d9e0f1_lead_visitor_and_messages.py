"""B4 获客：leads 加访客哈希/地区，新建 lead_messages

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Create Date: 2026-11-23

只存加盐哈希与省市，不存 IP 原文；留言走独立表，访客与运营共用，用 author_role 区分。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a6b7c8d9e0f1"
down_revision: Union[str, None] = "f5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("ip_hash", sa.String(length=64), nullable=True))
    op.add_column("leads", sa.Column("visitor_region", sa.String(length=64), nullable=True))
    op.create_index("ix_leads_project_ip_hash", "leads", ["project_id", "ip_hash"])

    op.create_table(
        "lead_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("author_role", sa.String(length=16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_lead_messages_project_id_projects", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["leads.id"], name="fk_lead_messages_lead_id_leads", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_lead_messages_created_by_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lead_messages_project_lead", "lead_messages", ["project_id", "lead_id", "created_at"]
    )
    op.create_index(
        "ix_lead_messages_project_unread", "lead_messages", ["project_id", "is_read"]
    )


def downgrade() -> None:
    op.drop_index("ix_lead_messages_project_unread", table_name="lead_messages")
    op.drop_index("ix_lead_messages_project_lead", table_name="lead_messages")
    op.drop_table("lead_messages")
    op.drop_index("ix_leads_project_ip_hash", table_name="leads")
    op.drop_column("leads", "visitor_region")
    op.drop_column("leads", "ip_hash")
