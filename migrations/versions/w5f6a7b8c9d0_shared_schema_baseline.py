"""shared database migration baseline at w5f6a7b8c9d0

Revision ID: w5f6a7b8c9d0
Revises: p8e9f0a1b2c3
Create Date: 2026-11-18

共享开发库已经由同事的分支推进到 w5f6a7b8c9d0，其中包含了轮次分析快照、
问题版本语义、样本分析版本、品牌匹配证据、引用分类与无答案面等结构。
本分支不再重复创建这些对象，只把该 head 作为基线接在 p0 增量迁移之前：

    p8e9f0a1b2c3 -> w5f6a7b8c9d0（本基线）-> q9a0b1c2d3e4 -> ... -> y7e8f9a0b1c2

本文件不执行 DDL；共享库上实际存在的同事专用表/列由同事分支维护。
p0 自己需要的表、列和约束全部在 q9a 之后的增量迁移里幂等补齐。
"""

from typing import Sequence, Union

revision: str = "w5f6a7b8c9d0"
down_revision: Union[str, None] = "p8e9f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
