"""channel primary domain unique per project

Revision ID: l2d3e4f5a6b7
Revises: k1c2d3e4f5a6
Create Date: 2026-11-17 21:00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "l2d3e4f5a6b7"
down_revision: Union[str, None] = "k1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 只约束“已填写主域名”的渠道；primary_domain 为空的候选渠道可并存。
    op.create_index(
        "uq_channels_project_primary_domain",
        "channels",
        ["project_id", "primary_domain"],
        unique=True,
        postgresql_where="primary_domain IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_index("uq_channels_project_primary_domain", table_name="channels")
