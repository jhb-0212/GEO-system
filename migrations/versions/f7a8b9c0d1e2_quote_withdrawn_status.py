"""媒体报价增加 withdrawn 状态：待审批可撤回，不删除记录

Revision ID: f7a8b9c0d1e2
Revises: e1f2a3b4c5d6
Create Date: 2026-11-20
"""

from typing import Sequence, Union

from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT = "ck_media_quotes_quote_status"


def upgrade() -> None:
    # 表由 SAEnum(create_constraint=True) 建约束，实际名已被命名约定固定；
    # 直接写 DDL，避免 Alembic 再套一层 ck_<table>_ 前缀。
    op.execute(f"ALTER TABLE media_quotes DROP CONSTRAINT IF EXISTS {CONSTRAINT}")
    op.execute(
        f"ALTER TABLE media_quotes ADD CONSTRAINT {CONSTRAINT} "
        "CHECK (status IN ('pending', 'approved', 'rejected', 'withdrawn'))"
    )


def downgrade() -> None:
    # 撤回是终态；回退旧约束前把 withdrawn 归到 rejected，保留“未通过”语义。
    op.execute("UPDATE media_quotes SET status = 'rejected' WHERE status = 'withdrawn'")
    op.execute(f"ALTER TABLE media_quotes DROP CONSTRAINT IF EXISTS {CONSTRAINT}")
    op.execute(
        f"ALTER TABLE media_quotes ADD CONSTRAINT {CONSTRAINT} "
        "CHECK (status IN ('pending', 'approved', 'rejected'))"
    )
