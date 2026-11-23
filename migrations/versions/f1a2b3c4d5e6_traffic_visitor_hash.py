"""B3 流量：traffic_events 补 IP 哈希与地区

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
Create Date: 2026-11-23

只加列与索引，不回填历史数据：历史事件没有 IP，hash 为空即为「未知」，
统计时只计入 PV，不参与去重访客。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e0f1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("traffic_events", sa.Column("visitor_ip_hash", sa.String(length=64), nullable=True))
    op.add_column("traffic_events", sa.Column("visitor_region", sa.String(length=64), nullable=True))
    op.create_index(
        "ix_traffic_events_project_ip_hash", "traffic_events", ["project_id", "visitor_ip_hash"]
    )


def downgrade() -> None:
    op.drop_index("ix_traffic_events_project_ip_hash", table_name="traffic_events")
    op.drop_column("traffic_events", "visitor_region")
    op.drop_column("traffic_events", "visitor_ip_hash")
