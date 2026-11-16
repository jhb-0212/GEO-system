"""add publish task trace id

Revision ID: 9d3e5f7a1b20
Revises: 7c1d9e2a4b60
Create Date: 2026-11-16 16:05:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9d3e5f7a1b20"
down_revision: Union[str, None] = "7c1d9e2a4b60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("publish_tasks", sa.Column("trace_id", sa.String(length=32), nullable=True))
    op.create_index("ix_publish_tasks_trace_id", "publish_tasks", ["trace_id"])

    # 老数据回填：内容版本只关联到唯一 trace 时才继承，多个 trace 保持空。
    op.execute(
        """
        UPDATE publish_tasks pt
        SET trace_id = sub.trace_id
        FROM (
            SELECT
                cvc.version_id,
                MIN(mc.trace_id) AS trace_id,
                COUNT(DISTINCT mc.trace_id) AS trace_count
            FROM content_version_citations cvc
            JOIN monitoring_citations mc ON mc.id = cvc.citation_id
            WHERE mc.trace_id IS NOT NULL
            GROUP BY cvc.version_id
        ) sub
        WHERE pt.version_id = sub.version_id
          AND sub.trace_count = 1
          AND pt.trace_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_publish_tasks_trace_id", table_name="publish_tasks")
    op.drop_column("publish_tasks", "trace_id")
