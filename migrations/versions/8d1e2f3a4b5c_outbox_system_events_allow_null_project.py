"""outbox_system_events_allow_null_project

Revision ID: 8d1e2f3a4b5c
Revises: 3f9c1d2e4b57
Create Date: 2026-11-10 18:40:00.000000

系统级事件（引擎目录同步、权限矩阵同步）没有项目归属，原 `project_id NOT NULL`
会把它们卡在入队处。本迁移放开可空，并用 CHECK 锁死边界：
有项目的事件随便，没项目的事件 topic 必须以 `system.` 开头。

回滚会先丢弃 `project_id IS NULL` 的系统级队列行（只是未投递的队列数据，
审计另行保存在 audit_logs），再把列改回 NOT NULL，保证 downgrade 可重复。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "8d1e2f3a4b5c"
down_revision: Union[str, None] = "3f9c1d2e4b57"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT_NAME = "ck_outbox_events_project_or_system"


def upgrade() -> None:
    op.alter_column("outbox_events", "project_id", existing_type=sa.Uuid(), nullable=True)
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "outbox_events",
        "project_id IS NOT NULL OR topic LIKE 'system.%'",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "outbox_events", type_="check")
    op.execute("DELETE FROM outbox_events WHERE project_id IS NULL")
    op.alter_column("outbox_events", "project_id", existing_type=sa.Uuid(), nullable=False)
