"""add deepseek websearch protocol

Revision ID: d6f7a8b9c0d1
Revises: c4d5e6f7a8b9
Create Date: 2026-11-16 21:40:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "d6f7a8b9c0d1"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHECK_NAME = "engine_protocol"  # 裸名；naming_convention 会生成 ck_ai_engine_entries_engine_protocol
NEW_VALUES = "('openai_compatible', 'yuanbao_search', 'deepseek_websearch', 'custom')"
OLD_VALUES = "('openai_compatible', 'yuanbao_search', 'custom')"


def upgrade() -> None:
    op.drop_constraint(CHECK_NAME, "ai_engine_entries", type_="check")
    op.create_check_constraint(
        CHECK_NAME,
        "ai_engine_entries",
        f"protocol IN {NEW_VALUES}",
    )


def downgrade() -> None:
    # 降级前必须先把使用新协议的入口改回 custom，否则重建旧约束会失败。
    op.drop_constraint(CHECK_NAME, "ai_engine_entries", type_="check")
    op.create_check_constraint(
        CHECK_NAME,
        "ai_engine_entries",
        f"protocol IN {OLD_VALUES}",
    )
