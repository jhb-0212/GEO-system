"""监测任务执行租约与执行尝试记录

Revision ID: n5a6b7c8d9e0
Revises: m4f5a6b7c8d9
"""

from alembic import op
import sqlalchemy as sa

revision = "n5a6b7c8d9e0"
down_revision = "m4f5a6b7c8d9"
branch_labels = None
depends_on = None

TASK_STATUSES = ("pending", "running", "done", "failed", "cancelled", "uncertain")


def upgrade() -> None:
    op.add_column(
        "monitoring_tasks", sa.Column("lease_owner", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "monitoring_tasks",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_constraint("task_status", "monitoring_tasks", type_="check")
    op.create_check_constraint(
        "task_status",
        "monitoring_tasks",
        "status IN (" + ", ".join(f"'{value}'" for value in TASK_STATUSES) + ")",
    )

    op.create_table(
        "monitoring_execution_attempts",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "claimed",
                "dispatching",
                "succeeded",
                "failed",
                "rate_limited",
                "lease_expired",
                "uncertain",
                name="attempt_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="claimed",
            nullable=False,
        ),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "failure_code",
            sa.Enum(
                "login_blocked",
                "timeout",
                "access_blocked",
                "captcha",
                "rate_limited",
                "other",
                name="attempt_failure_code",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_monitoring_execution_attempts_project_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["monitoring_tasks.id"],
            name=op.f("fk_monitoring_execution_attempts_task_id_monitoring_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_monitoring_execution_attempts")),
        sa.UniqueConstraint(
            "task_id", "attempt_no", name="uq_monitoring_attempts_task_attempt"
        ),
    )
    op.create_index(
        "ix_monitoring_attempts_status_lease",
        "monitoring_execution_attempts",
        ["status", "lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_monitoring_attempts_project_task",
        "monitoring_execution_attempts",
        ["project_id", "task_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_monitoring_attempts_project_task", table_name="monitoring_execution_attempts"
    )
    op.drop_index(
        "ix_monitoring_attempts_status_lease", table_name="monitoring_execution_attempts"
    )
    op.drop_table("monitoring_execution_attempts")
    op.drop_constraint("task_status", "monitoring_tasks", type_="check")
    op.create_check_constraint(
        "task_status",
        "monitoring_tasks",
        "status IN ('pending', 'running', 'done', 'failed', 'cancelled')",
    )
    op.drop_column("monitoring_tasks", "lease_expires_at")
    op.drop_column("monitoring_tasks", "lease_owner")
