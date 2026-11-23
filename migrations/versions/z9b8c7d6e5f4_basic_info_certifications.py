"""基础信息：users 加联系人字段 + certifications 资质表

Revision ID: z9b8c7d6e5f4
Revises: y9a8b7c6d5e4
Create Date: 2026-11-23

对标加快科技「知识库 → 基础信息」：联系人资料与资质证书。
资质到期状态不落库，读取时按 expires_on 现算，避免定时任务刷新。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "z9b8c7d6e5f4"
down_revision: Union[str, None] = "y9a8b7c6d5e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("phone", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("wechat", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("job_title", sa.String(length=64), nullable=True))

    op.create_table(
        "certifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("issuer", sa.String(length=255), nullable=True),
        sa.Column("cert_no", sa.String(length=128), nullable=True),
        sa.Column("issued_on", sa.Date(), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("evidence_url", sa.String(length=512), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_certifications_project_id_projects", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_certifications_created_by_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_certifications_project_active", "certifications", ["project_id", "is_active"])
    op.create_index("ix_certifications_project_expires", "certifications", ["project_id", "expires_on"])


def downgrade() -> None:
    op.drop_index("ix_certifications_project_expires", table_name="certifications")
    op.drop_index("ix_certifications_project_active", table_name="certifications")
    op.drop_table("certifications")
    op.drop_column("users", "job_title")
    op.drop_column("users", "wechat")
    op.drop_column("users", "phone")
