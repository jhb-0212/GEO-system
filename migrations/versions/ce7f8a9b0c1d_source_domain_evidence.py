"""Revision ID: ce7f8a9b0c1d
Revises: bd4e5f6a7b8c
Create Date: 2026-11-24
"""

from alembic import op
import sqlalchemy as sa

revision = "ce7f8a9b0c1d"
down_revision = "bd4e5f6a7b8c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_domain_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("site", sa.String(length=200), nullable=False),
        sa.Column("fetched_url", sa.String(length=500)),
        sa.Column("title", sa.String(length=200)),
        sa.Column("description", sa.Text()),
        sa.Column("sample_url", sa.String(length=500)),
        sa.Column("sample_title", sa.String(length=200)),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("detail", sa.String(length=120)),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "site", name="uq_source_domain_evidence_project_site"),
    )
    op.create_index(
        "ix_source_domain_evidence_project_status",
        "source_domain_evidence",
        ["project_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_source_domain_evidence_project_status", table_name="source_domain_evidence")
    op.drop_table("source_domain_evidence")
