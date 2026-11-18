"""Outbox 死信治理：outbox_events 增加 failure_count

Revision ID: p7d8e9f0a1b2
Revises: o6c7d8e9f0a1

说明：
- 投递失败计数，默认 0；达到配置上限后事件置 FAILED（死信），退出投递批次；
- 不加状态 CHECK（outbox_status 枚举已含 failed），避免既有数据迁移歧义。
"""

from alembic import op
import sqlalchemy as sa

revision = "p7d8e9f0a1b2"
down_revision = "o6c7d8e9f0a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outbox_events",
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("outbox_events", "failure_count")
