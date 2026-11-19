"""渠道负责人字段：首月运营把责任落到台账。

Revision ID: x7b8c9d0e1f2
Revises: x6a7b8c9d0e1
Create Date: 2026-11-19
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "x7b8c9d0e1f2"
down_revision = "x6a7b8c9d0e1"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    inspector = inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns("channels")}


def upgrade() -> None:
    existing = _columns()
    if "owner_name" not in existing:
        op.add_column("channels", sa.Column("owner_name", sa.String(length=128), nullable=True))
    if "owner_contact" not in existing:
        op.add_column(
            "channels", sa.Column("owner_contact", sa.String(length=255), nullable=True)
        )


def downgrade() -> None:
    existing = _columns()
    if "owner_contact" in existing:
        op.drop_column("channels", "owner_contact")
    if "owner_name" in existing:
        op.drop_column("channels", "owner_name")
