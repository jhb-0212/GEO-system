"""add deepseek_web_search protocol

Revision ID: f6d7e8f9a0b1
Revises: f5c6d7e8f9a0
Create Date: 2026-11-17 15:40:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "f6d7e8f9a0b1"
down_revision: Union[str, None] = "f5c6d7e8f9a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHECK_NAME = "engine_protocol"  # 裸名；naming_convention 会生成 ck_ai_engine_entries_engine_protocol
NEW_VALUES = (
    "('openai_compatible', 'yuanbao_search', 'deepseek_websearch', "
    "'deepseek_search', 'deepseek_web_search', 'doubao_search', 'wenxin_search', 'custom')"
)
PREV_VALUES = (
    "('openai_compatible', 'yuanbao_search', 'deepseek_websearch', "
    "'deepseek_search', 'doubao_search', 'wenxin_search', 'custom')"
)


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
        f"protocol IN {PREV_VALUES}",
    )
