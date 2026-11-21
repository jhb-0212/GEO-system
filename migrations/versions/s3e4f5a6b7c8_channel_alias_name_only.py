"""allow channel alias rows without a domain for old-name history

Revision ID: s3e4f5a6b7c8
Revises: r98d3e4f5a6b
Create Date: 2026-11-21

改名但渠道没有旧主域名时，旧名称仍要有一条结构化记录，不能只写备注。
`channel_aliases.domain` 允许为空；`alias_name` 有值时表示历史名称。
"""

import sqlalchemy as sa
from alembic import op

revision = "s3e4f5a6b7c8"
down_revision = "r98d3e4f5a6b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "channel_aliases",
        "domain",
        existing_type=sa.String(length=255),
        nullable=True,
    )


def downgrade() -> None:
    # 旧结构无法表达“只有名称、没有域名”的历史行；先清理再恢复非空约束。
    op.execute("DELETE FROM channel_aliases WHERE domain IS NULL")
    op.alter_column(
        "channel_aliases",
        "domain",
        existing_type=sa.String(length=255),
        nullable=False,
    )
