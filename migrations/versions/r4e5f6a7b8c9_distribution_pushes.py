"""事实推送记录表 distribution_pushes（G9）。

Revision ID: r4e5f6a7b8c9
Revises: t3c4d5e6f7a8
Create Date: 2026-11-25

一张表，两个唯一约束：
- `(project_id, fact_id, target_type, target_ref)`：同一事实对同一目标只留一条记录，
  重复推送复用记录而不是再造一行（否则「推送历史」会变成外发次数统计）；
- `(project_id, idempotency_key)`：键由事实 + 目标哈希得出，跨库/重放也不会撞。

`target_ref` 用空串而非 NULL：Postgres 唯一约束对 NULL 不去重，留 NULL 会让
`unique(project_id, fact_id, target_type, target_ref)` 对百科方向彻底失效。
"""

import app.models  # noqa: F401  注册所有模型到 Base.metadata
from alembic import op

from app.db.base import Base

revision = "r4e5f6a7b8c9"
down_revision = "t3c4d5e6f7a8"


def upgrade() -> None:
    Base.metadata.tables["distribution_pushes"].create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.tables["distribution_pushes"].drop(op.get_bind(), checkfirst=True)
