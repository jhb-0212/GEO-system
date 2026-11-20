"""持久化业务编号：任务、样本、发布、线索、事实陈述、审计

Revision ID: e1f2a3b4c5d6
Revises: aa1b2c3d4e5
Create Date: 2026-11-19

编号口径：
- 每类对象一条独立 PostgreSQL 序列，从 1 开始；
- 存量记录按 created_at, id 升序回填，最老为 1，最新最大；
- serial_no 唯一且非空，新建记录由数据库默认值分配，不依赖页面筛选或分页。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "aa1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SERIAL_TABLES = (
    ("monitoring_tasks", "monitoring_tasks_serial_no_seq"),
    ("monitoring_samples", "monitoring_samples_serial_no_seq"),
    ("publish_tasks", "publish_tasks_serial_no_seq"),
    ("leads", "leads_serial_no_seq"),
    ("answer_fact_claims", "answer_fact_claims_serial_no_seq"),
    ("audit_logs", "audit_logs_serial_no_seq"),
)


def _add_serial(table: str, sequence: str) -> None:
    op.add_column(table, sa.Column("serial_no", sa.Integer(), nullable=True))
    op.execute(
        sa.text(
            f"""
            WITH numbered AS (
                SELECT id, row_number() OVER (ORDER BY created_at, id) AS n
                FROM {table}
            )
            UPDATE {table} AS target
            SET serial_no = numbered.n
            FROM numbered
            WHERE target.id = numbered.id
            """
        )
    )
    op.execute(sa.text(f"CREATE SEQUENCE {sequence} OWNED BY {table}.serial_no"))
    op.execute(
        sa.text(
            f"SELECT setval('{sequence}', "
            f"COALESCE((SELECT MAX(serial_no) FROM {table}), 0) + 1, false)"
        )
    )
    op.alter_column(
        table,
        "serial_no",
        existing_type=sa.Integer(),
        nullable=False,
        server_default=sa.text(f"nextval('{sequence}')"),
    )
    op.create_unique_constraint(f"uq_{table}_serial_no", table, ["serial_no"])


def upgrade() -> None:
    for table, sequence in SERIAL_TABLES:
        _add_serial(table, sequence)


def downgrade() -> None:
    for table, sequence in reversed(SERIAL_TABLES):
        op.drop_constraint(f"uq_{table}_serial_no", table, type_="unique")
        op.alter_column(
            table,
            "serial_no",
            existing_type=sa.Integer(),
            nullable=True,
            server_default=None,
        )
        op.drop_column(table, "serial_no")
        op.execute(sa.text(f"DROP SEQUENCE IF EXISTS {sequence}"))
