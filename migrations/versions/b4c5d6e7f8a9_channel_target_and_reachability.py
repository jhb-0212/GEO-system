"""投喂目标改口径 + 回执可访问三态字段。

Revision ID: b4c5d6e7f8a9
Revises: b3c4d5e6f7a8
Create Date: 2026-11-23

两件事一次迁移做完：

1. `distribution_batches.target_engines` 拆成 `target_channel_ids`（目标，必填）与
   `expected_engines`（期望，可选）。历史数据的引擎列表原样搬到 expected_engines，
   目标渠道留空——需要人工补渠道，不猜。
2. `publish_receipts` 补「可访问」四列：last_reachable / status / error / at。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "distribution_batches",
        sa.Column(
            "target_channel_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "distribution_batches",
        sa.Column(
            "expected_engines",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    # 历史批次：原引擎列表迁到「期望」，目标渠道不猜、留空待补
    op.execute(
        "UPDATE distribution_batches SET expected_engines = target_engines WHERE target_engines IS NOT NULL"
    )
    op.drop_column("distribution_batches", "target_engines")

    op.add_column("publish_receipts", sa.Column("last_reachable", sa.Boolean(), nullable=True))
    op.add_column(
        "publish_receipts", sa.Column("last_reachability_status", sa.Integer(), nullable=True)
    )
    op.add_column(
        "publish_receipts", sa.Column("last_reachability_error", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "publish_receipts",
        sa.Column("last_reachability_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("publish_receipts", "last_reachability_at")
    op.drop_column("publish_receipts", "last_reachability_error")
    op.drop_column("publish_receipts", "last_reachability_status")
    op.drop_column("publish_receipts", "last_reachable")

    op.add_column(
        "distribution_batches",
        sa.Column(
            "target_engines",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.execute(
        "UPDATE distribution_batches SET target_engines = expected_engines WHERE expected_engines IS NOT NULL"
    )
    op.drop_column("distribution_batches", "expected_engines")
    op.drop_column("distribution_batches", "target_channel_ids")
