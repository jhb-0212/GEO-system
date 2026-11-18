"""引用证据扩列、未知信源审核队列与每轮统计快照。

Revision ID: s1c2d3e4f5a6
Revises: r0b1c2d3e4f5
Create Date: 2026-11-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "s1c2d3e4f5a6"
down_revision = "r0b1c2d3e4f5"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table)}


def _tables() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def upgrade() -> None:
    columns = _columns("monitoring_citations")
    if "title" not in columns:
        op.add_column("monitoring_citations", sa.Column("title", sa.String(length=512)))
    if "position" not in columns:
        op.add_column("monitoring_citations", sa.Column("position", sa.Integer()))
    if "source_category" not in columns:
        op.add_column(
            "monitoring_citations",
            sa.Column(
                "source_category",
                sa.Enum(
                    "brand_owned",
                    "competitor_owned",
                    "social_community",
                    "content_platform",
                    "news_media",
                    "industry_media",
                    "government_institution",
                    "education_institution",
                    "reference",
                    "ecommerce",
                    "other",
                    "unknown",
                    name="citation_source_category",
                    native_enum=False,
                    create_constraint=True,
                    length=32,
                ),
            ),
        )
    if "page_type" not in columns:
        op.add_column(
            "monitoring_citations",
            sa.Column(
                "page_type",
                sa.Enum(
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
                    name="citation_page_type",
                    native_enum=False,
                    create_constraint=True,
                    length=32,
                ),
            ),
        )
    if "classification_source" not in columns:
        op.add_column(
            "monitoring_citations",
            sa.Column(
                "classification_source",
                sa.Enum(
                    "rule",
                    "manual",
                    name="citation_classification_source",
                    native_enum=False,
                    create_constraint=True,
                    length=32,
                ),
            ),
        )
    if "classification_rule_version" not in columns:
        op.add_column(
            "monitoring_citations",
            sa.Column("classification_rule_version", sa.String(length=32)),
        )
    if "provider_fields" not in columns:
        op.add_column(
            "monitoring_citations",
            sa.Column("provider_fields", postgresql.JSONB(astext_type=sa.Text())),
        )

    if "citation_source_reviews" not in _tables():
        op.create_table(
            "citation_source_reviews",
            sa.Column("project_id", sa.Uuid(), nullable=False),
            sa.Column("domain", sa.String(length=255), nullable=False),
            sa.Column(
                "status",
                sa.Enum(
                    "pending",
                    "classified",
                    "ignored",
                    name="source_review_status",
                    native_enum=False,
                    create_constraint=True,
                    length=32,
                ),
                server_default="pending",
                nullable=False,
            ),
            sa.Column(
                "source_category",
                sa.Enum(
                    "brand_owned",
                    "competitor_owned",
                    "social_community",
                    "content_platform",
                    "news_media",
                    "industry_media",
                    "government_institution",
                    "education_institution",
                    "reference",
                    "ecommerce",
                    "other",
                    "unknown",
                    name="source_review_category",
                    native_enum=False,
                    create_constraint=True,
                    length=32,
                ),
            ),
            sa.Column(
                "suggested_source_category",
                sa.Enum(
                    "brand_owned",
                    "competitor_owned",
                    "social_community",
                    "content_platform",
                    "news_media",
                    "industry_media",
                    "government_institution",
                    "education_institution",
                    "reference",
                    "ecommerce",
                    "other",
                    "unknown",
                    name="source_review_suggested_category",
                    native_enum=False,
                    create_constraint=True,
                    length=32,
                ),
            ),
            sa.Column(
                "classification_source",
                sa.Enum(
                    "rule",
                    "manual",
                    name="source_review_classification_source",
                    native_enum=False,
                    create_constraint=True,
                    length=32,
                ),
            ),
            sa.Column("classification_rule_version", sa.String(length=32)),
            sa.Column("reviewed_by", sa.Uuid()),
            sa.Column("reviewed_at", sa.DateTime(timezone=True)),
            sa.Column("review_note", sa.Text()),
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("project_id", "domain", name="uq_citation_source_reviews_project_domain"),
        )
        op.create_index(
            "ix_citation_source_reviews_project_status",
            "citation_source_reviews",
            ["project_id", "status"],
        )

    if "stat_snapshots" not in _tables():
        op.create_table(
            "stat_snapshots",
            sa.Column("project_id", sa.Uuid(), nullable=False),
            sa.Column("round_id", sa.Uuid(), nullable=False),
            sa.Column("captured_by", sa.Uuid()),
            sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("scope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("definitions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("rule_version", sa.String(length=32), nullable=False),
            sa.Column("matcher_version", sa.String(length=32), nullable=False),
            sa.Column("classifier_version", sa.String(length=32), nullable=False),
            sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["round_id"], ["monitoring_rounds.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["captured_by"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("project_id", "round_id", name="uq_stat_snapshots_project_round"),
        )
        op.create_index(
            "ix_stat_snapshots_project_captured_at",
            "stat_snapshots",
            ["project_id", "captured_at"],
        )


def downgrade() -> None:
    if "stat_snapshots" in _tables():
        op.drop_table("stat_snapshots")
    if "citation_source_reviews" in _tables():
        op.drop_table("citation_source_reviews")
    columns = _columns("monitoring_citations")
    for name in (
        "provider_fields",
        "classification_rule_version",
        "classification_source",
        "page_type",
        "source_category",
        "position",
        "title",
    ):
        if name in columns:
            op.drop_column("monitoring_citations", name)
