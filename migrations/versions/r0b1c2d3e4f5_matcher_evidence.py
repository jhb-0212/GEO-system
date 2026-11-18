"""样本品牌匹配证据：matched_term / offset / evidence_text / list_rank / matcher_version

Revision ID: r0b1c2d3e4f5
Revises: q9a0b1c2d3e4
Create Date: 2026-11-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "r0b1c2d3e4f5"
down_revision = "q9a0b1c2d3e4"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("brand_match_kind", sa.String(length=16)),
    ("brand_match_term", sa.String(length=128)),
    ("brand_match_offset", sa.Integer()),
    ("brand_match_evidence", sa.Text()),
    ("brand_list_rank", sa.Integer()),
    ("matcher_version", sa.String(length=32)),
)


def _column_names(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    existing = _column_names("monitoring_samples")
    for name, column_type in _COLUMNS:
        if name not in existing:
            op.add_column("monitoring_samples", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    existing = _column_names("monitoring_samples")
    for name, _column_type in reversed(_COLUMNS):
        if name in existing:
            op.drop_column("monitoring_samples", name)
