"""align monitoring_samples.analysis_version to the p0 string contract

Revision ID: y7e8f9a0b1c2
Revises: 86b2358fd1ba
Create Date: 2026-11-18

共享库当前的 analysis_version 是 INTEGER，用来兼容早期只有数字版本号的样本；
p0 的规则版本是字符串（例如 substring-regex-v1），模型为 VARCHAR(32)。
本迁移把旧整数无损转成文本，已有历史值保留；新写入按字符串版本号落库。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "y7e8f9a0b1c2"
down_revision: Union[str, None] = "86b2358fd1ba"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column() -> dict | None:
    inspector = sa.inspect(op.get_bind())
    return next(
        (
            item
            for item in inspector.get_columns("monitoring_samples")
            if item["name"] == "analysis_version"
        ),
        None,
    )


def upgrade() -> None:
    column = _column()
    if column is None:
        op.add_column(
            "monitoring_samples",
            sa.Column("analysis_version", sa.String(length=32), nullable=True),
        )
        return
    column_type = column["type"]
    if isinstance(column_type, sa.String) and getattr(column_type, "length", None) == 32:
        return
    op.alter_column(
        "monitoring_samples",
        "analysis_version",
        existing_type=column_type,
        type_=sa.String(length=32),
        existing_nullable=column["nullable"],
        postgresql_using="analysis_version::text",
    )


def downgrade() -> None:
    # 字符串规则版本无法安全还原为整数，禁止自动降级以避免丢失版本语义。
    pass
