"""page-level publish approvals, admissions/recruitment page types

Revision ID: u6b7c8d9e0f1
Revises: t9a0b1c2d3e4
Create Date: 2026-11-21

逐页审批版：新增 page_approvals 台账，回执可挂 page_approval_id；引用页型和
公开页页型都增加 admissions / recruitment，并在发布回执入口对招生、招聘页做闸门。
"""

import sqlalchemy as sa
from alembic import op

revision = "u6b7c8d9e0f1"
down_revision = "t9a0b1c2d3e4"
branch_labels = None
depends_on = None

OLD_CITATION_PAGE_TYPES = (
    "homepage",
    "course_or_product",
    "article",
    "listicle",
    "how_to",
    "comparison",
    "review",
    "forum_or_qa",
    "video",
    "case_study",
    "faq",
    "search_surface",
    "other",
)
NEW_CITATION_PAGE_TYPES = OLD_CITATION_PAGE_TYPES + ("admissions", "recruitment")
OLD_PUBLIC_PAGE_TYPES = ("home", "course", "faq", "case", "contact", "other")
NEW_PUBLIC_PAGE_TYPES = OLD_PUBLIC_PAGE_TYPES + ("admissions", "recruitment")
PAGE_PERMISSIONS = ("official", "authorized", "third_party")
PAGE_APPROVAL_STATUSES = ("pending", "approved", "rejected", "revoked")


def _check_sql(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


def _drop_check_if_exists(table_name: str, *constraint_names: str) -> None:
    """删除旧 CHECK；兼容空库规范名与历史库重复命名，缺失时跳过。"""
    bind = op.get_bind()
    for name in constraint_names:
        bind.execute(
            sa.text(f'ALTER TABLE {table_name} DROP CONSTRAINT IF EXISTS "{name}"')
        )


def upgrade() -> None:
    # 1) 扩引用页型 + 公开页页型：先删旧 CHECK，扩值后重建。
    # 旧库可能把 Enum 名和历史命名约定叠成重复前缀，两种名字都要兼容。
    _drop_check_if_exists(
        "monitoring_citations",
        "ck_monitoring_citations_citation_page_type",
        "ck_monitoring_citations_ck_monitoring_citations_page_type",
    )
    op.create_check_constraint(
        op.f("ck_monitoring_citations_citation_page_type"),
        "monitoring_citations",
        _check_sql("page_type", NEW_CITATION_PAGE_TYPES),
    )
    _drop_check_if_exists("public_pages", "ck_public_pages_page_type")
    op.create_check_constraint(
        op.f("ck_public_pages_page_type"),
        "public_pages",
        _check_sql("page_type", NEW_PUBLIC_PAGE_TYPES),
    )

    # 2) 逐页审批台账。
    op.create_table(
        "page_approvals",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("page_url", sa.Text(), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("url_key", sa.String(length=512), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column(
            "page_type",
            sa.Enum(
                *NEW_CITATION_PAGE_TYPES,
                name="page_approval_page_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "permission",
            sa.Enum(
                *PAGE_PERMISSIONS,
                name="page_permission",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                *PAGE_APPROVAL_STATUSES,
                name="page_approval_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["channels.id"],
            name=op.f("fk_page_approvals_channel_id_channels"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_page_approvals_project_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name=op.f("fk_page_approvals_requested_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["users.id"],
            name=op.f("fk_page_approvals_reviewed_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_page_approvals")),
        sa.UniqueConstraint(
            "project_id", "channel_id", "url_key",
            name="uq_page_approvals_project_channel_url",
        ),
    )
    op.create_index(
        "ix_page_approvals_project_status",
        "page_approvals",
        ["project_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_page_approvals_project_page_type",
        "page_approvals",
        ["project_id", "page_type"],
        unique=False,
    )
    op.create_index(
        "ix_page_approvals_channel",
        "page_approvals",
        ["channel_id"],
        unique=False,
    )

    # 3) 回执挂审批凭证；已有回执保持空。
    op.add_column(
        "publish_receipts",
        sa.Column("page_approval_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_publish_receipts_page_approval_id",
        "publish_receipts",
        "page_approvals",
        ["page_approval_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_publish_receipts_page_approval_id",
        "publish_receipts",
        type_="foreignkey",
    )
    op.drop_column("publish_receipts", "page_approval_id")

    op.drop_index("ix_page_approvals_channel", table_name="page_approvals")
    op.drop_index("ix_page_approvals_project_page_type", table_name="page_approvals")
    op.drop_index("ix_page_approvals_project_status", table_name="page_approvals")
    op.drop_table("page_approvals")

    # 旧 CHECK 不接受新页型；降级前先归到 other。
    op.execute(
        "UPDATE monitoring_citations SET page_type='other' "
        "WHERE page_type IN ('admissions', 'recruitment')"
    )
    op.execute(
        "UPDATE public_pages SET page_type='other' "
        "WHERE page_type IN ('admissions', 'recruitment')"
    )
    _drop_check_if_exists(
        "monitoring_citations",
        "ck_monitoring_citations_citation_page_type",
        "ck_monitoring_citations_ck_monitoring_citations_page_type",
    )
    op.create_check_constraint(
        op.f("ck_monitoring_citations_citation_page_type"),
        "monitoring_citations",
        _check_sql("page_type", OLD_CITATION_PAGE_TYPES),
    )
    _drop_check_if_exists("public_pages", "ck_public_pages_page_type")
    op.create_check_constraint(
        op.f("ck_public_pages_page_type"),
        "public_pages",
        _check_sql("page_type", OLD_PUBLIC_PAGE_TYPES),
    )
