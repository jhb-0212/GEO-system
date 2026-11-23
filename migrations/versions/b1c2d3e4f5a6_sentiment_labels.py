"""情绪标注：sentiment_labels

Revision ID: b1c2d3e4f5a6
Revises: a0c1d2e3f4b5
Create Date: 2026-11-23

对标加快科技「测量层 → 情绪原文统计」：只存人工判定（正/中/负 + 备注），
原文与链接回读 monitoring_citations，不做副本，避免引用复核后情绪页展示旧文本。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a0c1d2e3f4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sentiment_labels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("citation_id", sa.Uuid(), nullable=False),
        sa.Column("polarity", sa.String(length=16), nullable=False),
        sa.Column("grade", sa.String(length=32), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("labeled_by", sa.Uuid(), nullable=True),
        sa.Column("labeled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "polarity IN ('positive', 'neutral', 'negative')",
            name="sentiment_polarity",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_sentiment_labels_project_id_projects", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["citation_id"], ["monitoring_citations.id"], name="fk_sentiment_labels_citation_id_monitoring_citations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["labeled_by"], ["users.id"], name="fk_sentiment_labels_labeled_by_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "citation_id", name="uq_sentiment_labels_project_citation"),
    )
    op.create_index("ix_sentiment_labels_project_polarity", "sentiment_labels", ["project_id", "polarity"])


def downgrade() -> None:
    op.drop_index("ix_sentiment_labels_project_polarity", table_name="sentiment_labels")
    op.drop_table("sentiment_labels")
