"""企业档案：项目级起草模型配置（company_draft_models）

Revision ID: u03d4e5f6a7b
Revises: t02c3d4e5f6a
Create Date: 2026-11-27

一键填表用的模型从「只读 .env」改成「可在系统里配」：一个项目一行，
Key 走 secrets_box 加密落库，接口只回显是否已配置。读取优先级是项目配置 >
DEEPSEEK_API_KEY > 引擎入口，所以老项目不配置也能继续用环境变量。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "u03d4e5f6a7b"
down_revision: Union[str, None] = "t02c3d4e5f6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "company_draft_models",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("base_url", sa.String(length=255), nullable=False, server_default="https://api.deepseek.com"),
        sa.Column("model", sa.String(length=128), nullable=False, server_default="deepseek-chat"),
        sa.Column("encrypted_secret", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_company_draft_models_project_id_projects",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name="fk_company_draft_models_updated_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_company_draft_models_project", "company_draft_models", ["project_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_company_draft_models_project", table_name="company_draft_models")
    op.drop_table("company_draft_models")
