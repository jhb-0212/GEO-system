"""内容状态：scheduled 改为字面 pending_publish

Revision ID: aa1b2c3d4e5
Revises: d9e0f1a2b3c4
Create Date: 2026-11-19
"""

from typing import Sequence, Union

from alembic import op

revision: str = "aa1b2c3d4e5"
down_revision: Union[str, None] = "d9e0f1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_STATUSES = (
    "draft",
    "pending_review",
    "approved",
    "rejected",
    "pending_publish",
    "published",
    "needs_attention",
    "archived",
)
OLD_STATUSES = (
    "draft",
    "pending_review",
    "approved",
    "rejected",
    "scheduled",
    "published",
    "needs_attention",
    "archived",
)
ITEMS_CHECK = "ck_content_items_content_status"
VERSIONS_CHECK = "ck_content_versions_content_version_status"


def _check_sql(statuses: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in statuses)
    return f"status IN ({quoted})"


def _drop_checks() -> None:
    # 约束名已是最终名，直接走 DDL，避免 Alembic 命名约定再套一层 ck_<table>_。
    op.execute(f"ALTER TABLE content_items DROP CONSTRAINT IF EXISTS {ITEMS_CHECK}")
    op.execute(f"ALTER TABLE content_versions DROP CONSTRAINT IF EXISTS {VERSIONS_CHECK}")


def _add_checks(statuses: tuple[str, ...]) -> None:
    op.execute(
        f"ALTER TABLE content_items ADD CONSTRAINT {ITEMS_CHECK} CHECK ({_check_sql(statuses)})"
    )
    op.execute(
        f"ALTER TABLE content_versions ADD CONSTRAINT {VERSIONS_CHECK} CHECK ({_check_sql(statuses)})"
    )


def upgrade() -> None:
    _drop_checks()
    op.execute("UPDATE content_items SET status = 'pending_publish' WHERE status = 'scheduled'")
    op.execute("UPDATE content_versions SET status = 'pending_publish' WHERE status = 'scheduled'")
    _add_checks(NEW_STATUSES)


def downgrade() -> None:
    _drop_checks()
    op.execute("UPDATE content_items SET status = 'scheduled' WHERE status = 'pending_publish'")
    op.execute("UPDATE content_versions SET status = 'scheduled' WHERE status = 'pending_publish'")
    _add_checks(OLD_STATUSES)
