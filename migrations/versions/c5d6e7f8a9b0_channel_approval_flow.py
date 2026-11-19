"""渠道准入审批流：准入状态 + 审批周期留痕表

Revision ID: c5d6e7f8a9b0
Revises: x7b8c9d0e1f2
Create Date: 2026-11-19

- `channels.approval_status` 与业务四态正交：pending_review / approved / rejected；
  既有历史渠道回填 `approved`（视为已准入），新建渠道默认 `pending_review`。
- `channel_approvals` 一行一个审批周期：提交人/提交时间/审批人/审批时间/结论/意见，
  驳回后重新提交追加新行，历史结论不覆盖。
- 未准入渠道不能建发布任务、不能挂接引用回执（门禁在应用层收口）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, None] = "x7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APPROVAL_STATUSES = ("pending_review", "approved", "rejected")
DECISIONS = ("approved", "rejected")


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"]: column for column in inspector.get_columns("channels")}

    if "approval_status" not in columns:
        op.add_column(
            "channels",
            sa.Column("approval_status", sa.String(length=32), nullable=True),
        )
    if "submitted_by" not in columns:
        op.add_column("channels", sa.Column("submitted_by", sa.Uuid(), nullable=True))
    if "submitted_at" not in columns:
        op.add_column("channels", sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
    if "reviewed_by" not in columns:
        op.add_column("channels", sa.Column("reviewed_by", sa.Uuid(), nullable=True))
    if "reviewed_at" not in columns:
        op.add_column("channels", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    if "decision_comment" not in columns:
        op.add_column("channels", sa.Column("decision_comment", sa.Text(), nullable=True))

    fk_constraints = {
        constraint["name"]
        for constraint in inspector.get_foreign_keys("channels")
    }
    if "fk_channels_submitted_by_users" not in fk_constraints:
        op.create_foreign_key(
            op.f("fk_channels_submitted_by_users"),
            "channels",
            "users",
            ["submitted_by"],
            ["id"],
            ondelete="SET NULL",
        )
    if "fk_channels_reviewed_by_users" not in fk_constraints:
        op.create_foreign_key(
            op.f("fk_channels_reviewed_by_users"),
            "channels",
            "users",
            ["reviewed_by"],
            ["id"],
            ondelete="SET NULL",
        )

    # 历史渠道视为已准入；新行由 server_default 进入待审核。
    op.execute(
        "UPDATE channels SET approval_status = 'approved' WHERE approval_status IS NULL"
    )
    op.alter_column(
        "channels",
        "approval_status",
        existing_type=sa.String(length=32),
        nullable=False,
        server_default="pending_review",
    )

    check_constraints = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("channels")
    }
    if "ck_channels_approval_status" not in check_constraints:
        op.create_check_constraint(
            "ck_channels_approval_status",
            "channels",
            f"approval_status IN ({', '.join(repr(v) for v in APPROVAL_STATUSES)})",
        )

    op.create_table(
        "channel_approvals",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("submitted_by", sa.Uuid(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
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
            name=op.f("fk_channel_approvals_project_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["channels.id"],
            name=op.f("fk_channel_approvals_channel_id_channels"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"],
            ["users.id"],
            name=op.f("fk_channel_approvals_submitted_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["users.id"],
            name=op.f("fk_channel_approvals_reviewed_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_channel_approvals")),
        sa.CheckConstraint(
            f"decision IS NULL OR decision IN ({', '.join(repr(v) for v in DECISIONS)})",
            name="ck_channel_approvals_decision",
        ),
    )
    op.create_index(
        "ix_channel_approvals_project_channel",
        "channel_approvals",
        ["project_id", "channel_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_channel_approvals_project_channel", table_name="channel_approvals")
    op.drop_table("channel_approvals")

    inspector = sa.inspect(op.get_bind())
    check_constraints = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("channels")
    }
    if "ck_channels_approval_status" in check_constraints:
        op.drop_constraint("ck_channels_approval_status", "channels", type_="check")

    fk_constraints = {
        constraint["name"]
        for constraint in inspector.get_foreign_keys("channels")
    }
    for fk in ("fk_channels_reviewed_by_users", "fk_channels_submitted_by_users"):
        if fk in fk_constraints:
            op.drop_constraint(op.f(fk), "channels", type_="foreignkey")

    for column in (
        "decision_comment",
        "reviewed_at",
        "reviewed_by",
        "submitted_at",
        "submitted_by",
        "approval_status",
    ):
        op.drop_column("channels", column)
