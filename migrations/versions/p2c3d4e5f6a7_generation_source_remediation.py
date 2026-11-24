"""生成批次来源放开第三个取值：`remediation`（负面原文 → 纠正稿）。

Revision ID: p2c3d4e5f6a7
Revises: o1b2c3d4e5f6
Create Date: 2026-11-24

为什么改约束：`generation_batches.source` 原来只允许 opportunity / question，
「舆情重大判定」这类模块我们自己不做，但**人已经判定为负面**的那条引用需要一个处置出口，
否则情绪标注只能停在标签上、没有下游动作。纠正稿仍然走生成批次（模板合成 + 人工审稿 +
不自动发布），只是选题证据从机会缺口换成一条人工确认过的引用，所以这里只放开枚举取值，
表结构与语义都不变。
"""

from alembic import op

revision = "p2c3d4e5f6a7"
down_revision = "o1b2c3d4e5f6"

OLD_SOURCES = "source in ('opportunity','question')"
NEW_SOURCES = "source in ('opportunity','question','remediation')"


def upgrade() -> None:
    op.drop_constraint("ck_generation_batches_source", "generation_batches", type_="check")
    op.create_check_constraint("ck_generation_batches_source", "generation_batches", NEW_SOURCES)


def downgrade() -> None:
    op.drop_constraint("ck_generation_batches_source", "generation_batches", type_="check")
    op.create_check_constraint("ck_generation_batches_source", "generation_batches", OLD_SOURCES)
