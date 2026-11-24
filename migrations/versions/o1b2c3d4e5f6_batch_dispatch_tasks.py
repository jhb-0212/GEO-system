"""批次生成发布任务：给批次加准入快照与任务数，给任务加批次回溯边。

Revision ID: o1b2c3d4e5f6
Revises: n0d1e2f3a4b5
Create Date: 2026-11-24

为什么加这三列：
- `publish_tasks.source_batch_id`：批次与任务之间原本没有任何关联，投喂过的内容
  在闭环看板（以任务为轴）、新鲜度（只认回执）、收录检测（只认回执 URL）里都看不见，
  掉进三张表的缝里。加这条边，四条链路自动覆盖批次。
- `distribution_batches.approval_snapshot`：渠道准入是调用时实时查库的，事后撤准入
  就无法解释当初为什么放行；冻结一份证据，一次写入不更新。
- `distribution_batches.task_count`：批次页要能直接回答「这一批生成了几条任务」，
  而不是让人再去数一遍。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "o1b2c3d4e5f6"
down_revision = "n0d1e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "distribution_batches",
        sa.Column("approval_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "distribution_batches",
        sa.Column("task_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "publish_tasks",
        sa.Column("source_batch_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_publish_tasks_source_batch", "publish_tasks", ["source_batch_id"], unique=False
    )
    op.create_foreign_key(
        "fk_publish_tasks_source_batch",
        "publish_tasks",
        "distribution_batches",
        ["source_batch_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_publish_tasks_source_batch", "publish_tasks", type_="foreignkey")
    op.drop_index("ix_publish_tasks_source_batch", table_name="publish_tasks")
    op.drop_column("publish_tasks", "source_batch_id")
    op.drop_column("distribution_batches", "task_count")
    op.drop_column("distribution_batches", "approval_snapshot")
