"""remove deepseek_search protocol

DeepSeek 主路径已切到 `deepseek_web_search`，`deepseek_search`（/v1/tools/search）
按用户决定永久删除：适配器、探针、入口与库约束取值一并移除。

Revision ID: j0b1c2d3e4f5
Revises: h8f9a0b1c2d3
Create Date: 2026-11-17 17:10:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "j0b1c2d3e4f5"
down_revision: Union[str, None] = "i9a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHECK_NAME = "engine_protocol"  # 裸名；naming_convention 生成 ck_ai_engine_entries_engine_protocol
NEW_VALUES = (
    "('openai_compatible', 'yuanbao_search', 'deepseek_web_search', "
    "'doubao_search', 'wenxin_search', 'custom')"
)
PREV_VALUES = (
    "('openai_compatible', 'yuanbao_search', 'deepseek_search', "
    "'deepseek_web_search', 'doubao_search', 'wenxin_search', 'custom')"
)


def upgrade() -> None:
    # 升级前必须确认库内没有 protocol='deepseek_search' 的入口，否则重建约束会失败。
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
