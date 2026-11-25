"""批次闸门记录表 generation_gate_results（批次级生成闸门）。

Revision ID: u5f6a7b8c9d0
Revises: r4e5f6a7b8c9
Create Date: 2026-11-25

只记录闸门结论（precheck / sample_review / approval）与依据，不改批次与生成项状态。
`blockers` 与 `metrics` 都用 JSONB：闸门规则会随批次策略演进，逐项拆列会让
「加一条体检项」都要迁移一次。
"""

import app.models  # noqa: F401  注册所有模型到 Base.metadata
from alembic import op

from app.db.base import Base

revision = "u5f6a7b8c9d0"
down_revision = "r4e5f6a7b8c9"


def upgrade() -> None:
    Base.metadata.tables["generation_gate_results"].create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.tables["generation_gate_results"].drop(op.get_bind(), checkfirst=True)
