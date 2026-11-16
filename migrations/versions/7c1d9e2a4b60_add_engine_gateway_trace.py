"""add engine gateway trace and raw request fields

Revision ID: 7c1d9e2a4b60
Revises: 2fbc5b97e953
Create Date: 2026-11-16 15:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "7c1d9e2a4b60"
down_revision: Union[str, None] = "2fbc5b97e953"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("monitoring_tasks", sa.Column("trace_id", sa.String(length=32), nullable=True))
    op.create_index("ix_monitoring_tasks_trace_id", "monitoring_tasks", ["trace_id"])

    op.add_column("monitoring_samples", sa.Column("trace_id", sa.String(length=32), nullable=True))
    op.add_column(
        "monitoring_samples",
        sa.Column("request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("monitoring_samples", sa.Column("latency_ms", sa.Integer(), nullable=True))
    op.add_column("monitoring_samples", sa.Column("prompt_tokens", sa.Integer(), nullable=True))
    op.add_column("monitoring_samples", sa.Column("completion_tokens", sa.Integer(), nullable=True))
    op.add_column("monitoring_samples", sa.Column("total_tokens", sa.Integer(), nullable=True))
    op.add_column(
        "monitoring_samples", sa.Column("estimated_cost_cny", sa.Numeric(14, 6), nullable=True)
    )
    op.add_column(
        "monitoring_samples", sa.Column("gateway_version", sa.String(length=32), nullable=True)
    )
    op.create_index("ix_monitoring_samples_trace_id", "monitoring_samples", ["trace_id"])

    op.add_column("monitoring_citations", sa.Column("trace_id", sa.String(length=32), nullable=True))
    op.create_index("ix_monitoring_citations_trace_id", "monitoring_citations", ["trace_id"])

    # 老数据回填：任务用 id 去横线当 trace_id，样本/引用沿任务继承，避免全空。
    op.execute(
        "UPDATE monitoring_tasks SET trace_id = replace(id::text, '-', '') "
        "WHERE trace_id IS NULL"
    )
    op.execute(
        "UPDATE monitoring_samples s SET trace_id = t.trace_id "
        "FROM monitoring_tasks t WHERE s.task_id = t.id AND s.trace_id IS NULL"
    )
    op.execute(
        "UPDATE monitoring_citations c SET trace_id = s.trace_id "
        "FROM monitoring_samples s WHERE c.sample_id = s.id AND c.trace_id IS NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_monitoring_citations_trace_id", table_name="monitoring_citations")
    op.drop_column("monitoring_citations", "trace_id")

    op.drop_index("ix_monitoring_samples_trace_id", table_name="monitoring_samples")
    op.drop_column("monitoring_samples", "gateway_version")
    op.drop_column("monitoring_samples", "estimated_cost_cny")
    op.drop_column("monitoring_samples", "total_tokens")
    op.drop_column("monitoring_samples", "completion_tokens")
    op.drop_column("monitoring_samples", "prompt_tokens")
    op.drop_column("monitoring_samples", "latency_ms")
    op.drop_column("monitoring_samples", "request_payload")
    op.drop_column("monitoring_samples", "trace_id")

    op.drop_index("ix_monitoring_tasks_trace_id", table_name="monitoring_tasks")
    op.drop_column("monitoring_tasks", "trace_id")
