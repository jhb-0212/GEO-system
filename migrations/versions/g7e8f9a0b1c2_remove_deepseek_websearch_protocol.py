"""remove deepseek_websearch protocol

Revision ID: g7e8f9a0b1c2
Revises: f6d7e8f9a0b1
Create Date: 2026-11-17 16:10:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "g7e8f9a0b1c2"
down_revision: Union[str, None] = "f6d7e8f9a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHECK_NAME = "engine_protocol"  # 裸名；naming_convention 会生成 ck_ai_engine_entries_engine_protocol
NEW_VALUES = (
    "('openai_compatible', 'yuanbao_search', 'deepseek_search', "
    "'deepseek_web_search', 'doubao_search', 'wenxin_search', 'custom')"
)
PREV_VALUES = (
    "('openai_compatible', 'yuanbao_search', 'deepseek_websearch', "
    "'deepseek_search', 'deepseek_web_search', 'doubao_search', 'wenxin_search', 'custom')"
)


def upgrade() -> None:
    # 升级前必须确认库里没有 protocol=deepseek_websearch 的入口，否则重建约束会失败。
    op.drop_constraint(CHECK_NAME, "ai_engine_entries", type_="check")
    op.create_check_constraint(
        CHECK_NAME,
        "ai_engine_entries",
        f"protocol IN {NEW_VALUES}",
    )


def downgrade() -> None:
    op.drop_constraint(CHECK_NAME, "ai_engine_entries", type_="check")
    op.create_check_constraint(
        CHECK_NAME,
        "ai_engine_entries",
        f"protocol IN {PREV_VALUES}",
    )
