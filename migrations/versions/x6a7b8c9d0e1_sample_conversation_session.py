"""sample conversation session identity

Revision ID: x6a7b8c9d0e1
Revises: a9b0c1d2e3f4, z8e9f0a1b2c3
Create Date: 2026-11-19

P60 要求逐题新开对话并记录联网模式。`sampling_mode` 已记录联网模式，本迁移补
`conversation_id` / `conversation_mode`：
- `conversation_id` 每个样本唯一，项目内唯一约束直接阻止跨题复用；
- `conversation_mode` 区分 `stateless`（API 每次独立请求）、`fresh`（网页端新开对话）、
  `manual`（人工录入）。
历史样本按样本 ID 回填唯一会话键；手工样本按 gateway_version=manual 标记。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "x6a7b8c9d0e1"
down_revision: Union[tuple[str, str], None] = ("a9b0c1d2e3f4", "z8e9f0a1b2c3")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"]: column for column in inspector.get_columns("monitoring_samples")}
    if "conversation_id" not in columns:
        op.add_column(
            "monitoring_samples",
            sa.Column("conversation_id", sa.String(length=64), nullable=True),
        )
    if "conversation_mode" not in columns:
        op.add_column(
            "monitoring_samples",
            sa.Column(
                "conversation_mode",
                sa.String(length=16),
                nullable=True,
                server_default="stateless",
            ),
        )
    op.execute(
        """
        UPDATE monitoring_samples AS s
        SET conversation_id = replace(s.id::text, '-', ''),
            conversation_mode = CASE
                WHEN s.gateway_version = 'manual' THEN 'manual'
                WHEN EXISTS (
                    SELECT 1
                    FROM monitoring_tasks AS t
                    JOIN ai_engine_entries AS e ON e.id = t.engine_entry_id
                    WHERE t.id = s.task_id AND e.entry_type = 'web_user'
                ) THEN 'fresh'
                ELSE 'stateless'
            END
        WHERE s.conversation_id IS NULL OR s.conversation_mode IS NULL
        """
    )
    op.alter_column(
        "monitoring_samples",
        "conversation_id",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.alter_column(
        "monitoring_samples",
        "conversation_mode",
        existing_type=sa.String(length=16),
        nullable=False,
        server_default="stateless",
    )
    unique_constraints = {
        constraint["name"] for constraint in inspector.get_unique_constraints("monitoring_samples")
    }
    if "uq_monitoring_samples_project_conversation" not in unique_constraints:
        op.create_unique_constraint(
            "uq_monitoring_samples_project_conversation",
            "monitoring_samples",
            ["project_id", "conversation_id"],
        )
    check_constraints = {
        constraint["name"] for constraint in inspector.get_check_constraints("monitoring_samples")
    }
    if "ck_monitoring_samples_conversation_mode" not in check_constraints:
        op.create_check_constraint(
            "ck_monitoring_samples_conversation_mode",
            "monitoring_samples",
            "conversation_mode IN ('stateless', 'fresh', 'manual')",
        )


def downgrade() -> None:
    op.drop_constraint(
        "ck_monitoring_samples_conversation_mode",
        "monitoring_samples",
        type_="check",
    )
    op.drop_constraint(
        "uq_monitoring_samples_project_conversation",
        "monitoring_samples",
        type_="unique",
    )
    op.drop_column("monitoring_samples", "conversation_mode")
    op.drop_column("monitoring_samples", "conversation_id")
