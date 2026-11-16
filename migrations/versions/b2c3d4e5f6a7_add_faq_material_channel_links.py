"""add faq material and channel publish urls

Revision ID: b2c3d4e5f6a7
Revises: 9d3e5f7a1b20
Create Date: 2026-11-16 18:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "9d3e5f7a1b20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


faq_status = sa.Enum(
    "draft",
    "published",
    "unpublished",
    name="faq_status",
    native_enum=False,
    length=32,
    create_constraint=True,
)

material_category = sa.Enum(
    "image",
    "document",
    "case",
    name="material_category",
    native_enum=False,
    length=32,
    create_constraint=True,
)


def upgrade() -> None:
    op.add_column("channels", sa.Column("publish_url", sa.String(length=512), nullable=True))
    op.add_column("channels", sa.Column("login_url", sa.String(length=512), nullable=True))

    op.create_table(
        "faqs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("question", sa.String(length=255), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("status", faq_status, nullable=False, server_default="draft"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_faqs_project_status", "faqs", ["project_id", "status"])

    op.create_table(
        "materials",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("category", material_category, nullable=False, server_default="document"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_materials_project_category", "materials", ["project_id", "category"])


def downgrade() -> None:
    op.drop_index("ix_materials_project_category", table_name="materials")
    op.drop_table("materials")
    op.drop_index("ix_faqs_project_status", table_name="faqs")
    op.drop_table("faqs")
    op.drop_column("channels", "login_url")
    op.drop_column("channels", "publish_url")
