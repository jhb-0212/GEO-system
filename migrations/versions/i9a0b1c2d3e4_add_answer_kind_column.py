"""add monitoring_samples.answer_kind

模型 `MonitoringSample.answer_kind` 早已声明并参与写入，但迁移链一直没有建这一列，
导致生产库与模型不一致（SELECT/INSERT 会报不明列）。本迁移补列并回填历史样本。

Revision ID: i9a0b1c2d3e4
Revises: h8f9a0b1c2d3
Create Date: 2026-11-17 16:40:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i9a0b1c2d3e4"
down_revision: Union[str, None] = "h8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHECK_NAME = "answer_kind"  # 裸名；naming_convention 生成 ck_monitoring_samples_answer_kind
ALLOWED_VALUES = "('answer', 'search_result')"


def upgrade() -> None:
    op.add_column(
        "monitoring_samples",
        sa.Column("answer_kind", sa.String(length=32), nullable=True),
    )
    op.create_check_constraint(
        CHECK_NAME,
        "monitoring_samples",
        f"answer_kind IN {ALLOWED_VALUES}",
    )
    # 历史样本：从 raw_response 里已有的 answer_kind 回填；未声明的保持 NULL（执行前占位）。
    op.execute(
        """
        UPDATE monitoring_samples
        SET answer_kind = raw_response ->> 'answer_kind'
        WHERE answer_kind IS NULL
          AND raw_response IS NOT NULL
          AND raw_response ->> 'answer_kind' IN ('answer', 'search_result')
        """
    )


def downgrade() -> None:
    op.drop_constraint(CHECK_NAME, "monitoring_samples", type_="check")
    op.drop_column("monitoring_samples", "answer_kind")
