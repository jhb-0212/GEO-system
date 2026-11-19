"""把监测历史字段与旧版留档表纳入迁移链，保证空库与现网结构一致。

Revision ID: d1e2f3a4b5c6
Revises: b7c8d9e0f1a2
Create Date: 2026-11-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d1e2f3a4b5c6"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None

_CITATION_COLUMNS = (
    ("citation_order", sa.Integer()),
    ("provider_payload", postgresql.JSONB(astext_type=sa.Text())),
    ("parse_version", sa.String(length=32)),
    (
        "is_domain_level",
        sa.Boolean(),
    ),
    (
        "source_category_source",
        sa.String(length=32),
    ),
    (
        "page_type_source",
        sa.String(length=32),
    ),
    ("classified_at", sa.DateTime(timezone=True)),
    ("classification_reviewed_by", sa.Uuid()),
    ("classification_reviewed_at", sa.DateTime(timezone=True)),
    ("classification_note", sa.Text()),
)


def _inspector():
    return sa.inspect(op.get_bind())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in _inspector().get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in _inspector().get_indexes(table)}


def _foreign_keys(table: str) -> set[str]:
    return {
        fk["name"]
        for fk in _inspector().get_foreign_keys(table)
        if fk.get("name")
    }


def _tables() -> set[str]:
    return set(_inspector().get_table_names())


def upgrade() -> None:
    columns = _columns("monitoring_citations")

    for name, column_type in _CITATION_COLUMNS:
        if name not in columns:
            if name == "is_domain_level":
                op.add_column(
                    "monitoring_citations",
                    sa.Column(
                        name,
                        column_type,
                        nullable=False,
                        server_default=sa.text("false"),
                    ),
                )
            elif name in {"source_category_source", "page_type_source"}:
                op.add_column(
                    "monitoring_citations",
                    sa.Column(
                        name,
                        column_type,
                        nullable=False,
                        server_default="unknown",
                    ),
                )
            else:
                op.add_column(
                    "monitoring_citations",
                    sa.Column(name, column_type),
                )

    # 现网已有 title 为 text；空库迁移链此前建的是 varchar(512)，这里统一为 text。
    op.alter_column(
        "monitoring_citations",
        "title",
        existing_type=sa.String(length=512),
        type_=sa.Text(),
    )

    op.alter_column(
        "monitoring_citations",
        "source_category",
        existing_type=sa.String(length=32),
        nullable=False,
        server_default="unknown",
    )
    op.alter_column(
        "monitoring_citations",
        "page_type",
        existing_type=sa.String(length=32),
        nullable=False,
        server_default="other",
    )

    if "brand_match_offset_end" not in _columns("monitoring_samples"):
        op.add_column(
            "monitoring_samples",
            sa.Column("brand_match_offset_end", sa.Integer()),
        )

    if "fk_monitoring_citations_classification_reviewed_by_users" not in _foreign_keys(
        "monitoring_citations"
    ):
        op.create_foreign_key(
            op.f("fk_monitoring_citations_classification_reviewed_by_users"),
            "monitoring_citations",
            "users",
            ["classification_reviewed_by"],
            ["id"],
            ondelete="SET NULL",
        )

    indexes = _indexes("monitoring_citations")
    if "ix_monitoring_citations_project_page_type" not in indexes:
        op.create_index(
            "ix_monitoring_citations_project_page_type",
            "monitoring_citations",
            ["project_id", "page_type"],
            unique=False,
        )
    if "ix_monitoring_citations_project_source_category" not in indexes:
        op.create_index(
            "ix_monitoring_citations_project_source_category",
            "monitoring_citations",
            ["project_id", "source_category"],
            unique=False,
        )

    if "monitoring_brand_mentions" not in _tables():
        op.create_table(
            "monitoring_brand_mentions",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("project_id", sa.Uuid(), nullable=False),
            sa.Column("sample_id", sa.Uuid(), nullable=False),
            sa.Column("brand_profile_id", sa.Uuid(), nullable=True),
            sa.Column("term", sa.String(length=255), nullable=False),
            sa.Column("term_type", sa.String(length=32), nullable=False),
            sa.Column("offset_start", sa.Integer(), nullable=False),
            sa.Column("offset_end", sa.Integer(), nullable=False),
            sa.Column("evidence_text", sa.Text(), nullable=True),
            sa.Column("sentence", sa.Text(), nullable=True),
            sa.Column("list_rank", sa.Integer(), nullable=True),
            sa.Column(
                "requires_review",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column("matcher_version", sa.String(length=32), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(
                ["brand_profile_id"],
                ["brand_profiles.id"],
                name=op.f("fk_monitoring_brand_mentions_brand_profile_id_brand_profiles"),
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["project_id"],
                ["projects.id"],
                name=op.f("fk_monitoring_brand_mentions_project_id_projects"),
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["sample_id"],
                ["monitoring_samples.id"],
                name=op.f("fk_monitoring_brand_mentions_sample_id_monitoring_samples"),
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_monitoring_brand_mentions")),
            sa.UniqueConstraint(
                "project_id",
                "sample_id",
                "term",
                "offset_start",
                name="uq_monitoring_brand_mentions_sample_term_offset",
            ),
        )
        op.create_index(
            "ix_monitoring_brand_mentions_project_sample",
            "monitoring_brand_mentions",
            ["project_id", "sample_id"],
            unique=False,
        )

    if "monitoring_source_profiles" not in _tables():
        op.create_table(
            "monitoring_source_profiles",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("project_id", sa.Uuid(), nullable=False),
            sa.Column("domain", sa.String(length=255), nullable=False),
            sa.Column("source_category", sa.String(length=32), nullable=False),
            sa.Column("suggested_source_category", sa.String(length=32), nullable=True),
            sa.Column("classification_rule_version", sa.String(length=32), nullable=True),
            sa.Column("reviewed_by", sa.Uuid(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(
                ["project_id"],
                ["projects.id"],
                name=op.f("fk_monitoring_source_profiles_project_id_projects"),
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["reviewed_by"],
                ["users.id"],
                name=op.f("fk_monitoring_source_profiles_reviewed_by_users"),
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_monitoring_source_profiles")),
            sa.UniqueConstraint(
                "project_id",
                "domain",
                name="uq_monitoring_source_profiles_project_domain",
            ),
        )
        op.create_index(
            "ix_monitoring_source_profiles_project_domain",
            "monitoring_source_profiles",
            ["project_id", "domain"],
            unique=False,
        )


def downgrade() -> None:
    # 本迁移只补齐历史结构，不删除现网已有的数据表。
    if "ix_monitoring_citations_project_source_category" in _indexes(
        "monitoring_citations"
    ):
        op.drop_index(
            "ix_monitoring_citations_project_source_category",
            table_name="monitoring_citations",
        )
    if "ix_monitoring_citations_project_page_type" in _indexes("monitoring_citations"):
        op.drop_index(
            "ix_monitoring_citations_project_page_type",
            table_name="monitoring_citations",
        )
    if "fk_monitoring_citations_classification_reviewed_by_users" in _foreign_keys(
        "monitoring_citations"
    ):
        op.drop_constraint(
            "fk_monitoring_citations_classification_reviewed_by_users",
            "monitoring_citations",
            type_="foreignkey",
        )

    for name, _ in reversed(_CITATION_COLUMNS):
        if name in _columns("monitoring_citations"):
            op.drop_column("monitoring_citations", name)

    if "brand_match_offset_end" in _columns("monitoring_samples"):
        op.drop_column("monitoring_samples", "brand_match_offset_end")

    op.alter_column(
        "monitoring_citations",
        "page_type",
        existing_type=sa.String(length=32),
        nullable=True,
        server_default=None,
    )
    op.alter_column(
        "monitoring_citations",
        "source_category",
        existing_type=sa.String(length=32),
        nullable=True,
        server_default=None,
    )
    op.alter_column(
        "monitoring_citations",
        "title",
        existing_type=sa.Text(),
        type_=sa.String(length=512),
    )
