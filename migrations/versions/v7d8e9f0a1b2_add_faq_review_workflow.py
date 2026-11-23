"""FAQ 审核闭环：pending_review / rejected 状态、审核意见、审核人

Revision ID: v7d8e9f0a1b2
Revises: u6b7c8d9e0f1
Create Date: 2026-11-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v7d8e9f0a1b2"
down_revision: Union[str, None] = "u6b7c8d9e0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT = "ck_faqs_faq_status"
OLD_STATUSES = ("draft", "published", "unpublished")
NEW_STATUSES = ("draft", "pending_review", "rejected", "published", "unpublished")


def _status_check(statuses: tuple[str, ...]) -> str:
    values = ", ".join(f"'{status}'" for status in statuses)
    return f"CHECK (status IN ({values}))"


def upgrade() -> None:
    op.add_column("faqs", sa.Column("review_comment", sa.Text(), nullable=True))
    op.add_column("faqs", sa.Column("reviewed_by", sa.Uuid(), nullable=True))
    op.add_column(
        "faqs", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_faqs_reviewed_by_users",
        "faqs",
        "users",
        ["reviewed_by"],
        ["id"],
        ondelete="SET NULL",
    )

    # 状态约束由 str_enum 生成，实际名按命名约定固定；直接改约束，避免新旧值混用。
    op.execute(f"ALTER TABLE faqs DROP CONSTRAINT IF EXISTS {CONSTRAINT}")
    op.execute(
        f"ALTER TABLE faqs ADD CONSTRAINT {CONSTRAINT} {_status_check(NEW_STATUSES)}"
    )


def downgrade() -> None:
    # 旧版本没有审核态：待审/驳回统一切回 draft，审核意见字段随列删除。
    op.execute("UPDATE faqs SET status = 'draft' WHERE status IN ('pending_review', 'rejected')")
    op.execute(f"ALTER TABLE faqs DROP CONSTRAINT IF EXISTS {CONSTRAINT}")
    op.execute(
        f"ALTER TABLE faqs ADD CONSTRAINT {CONSTRAINT} {_status_check(OLD_STATUSES)}"
    )
    op.drop_constraint("fk_faqs_reviewed_by_users", "faqs", type_="foreignkey")
    op.drop_column("faqs", "reviewed_at")
    op.drop_column("faqs", "reviewed_by")
    op.drop_column("faqs", "review_comment")
