"""Revision ID: k7b8c9d0e1f2
Revises: j6a7b8c9d0e1
Create Date: 2026-11-24

情感标注改为按「项目 + 引用 + 标注人」唯一，允许双人独立盲评。
部分开发库早期已落过 `_labeler` 约束，这里做幂等迁移，避免重复建。
"""

from alembic import op

revision = "k7b8c9d0e1f2"
down_revision = "j6a7b8c9d0e1"
branch_labels = None
depends_on = None

_UPGRADE = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'sentiment_labels'::regclass
          AND conname = 'uq_sentiment_labels_project_citation'
    ) THEN
        ALTER TABLE sentiment_labels DROP CONSTRAINT uq_sentiment_labels_project_citation;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'sentiment_labels'::regclass
          AND conname = 'uq_sentiment_labels_project_citation_labeler'
    ) THEN
        ALTER TABLE sentiment_labels
            ADD CONSTRAINT uq_sentiment_labels_project_citation_labeler
            UNIQUE (project_id, citation_id, labeled_by);
    END IF;
END $$;
"""

_DOWNGRADE = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'sentiment_labels'::regclass
          AND conname = 'uq_sentiment_labels_project_citation_labeler'
    ) THEN
        ALTER TABLE sentiment_labels DROP CONSTRAINT uq_sentiment_labels_project_citation_labeler;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'sentiment_labels'::regclass
          AND conname = 'uq_sentiment_labels_project_citation'
    ) THEN
        ALTER TABLE sentiment_labels
            ADD CONSTRAINT uq_sentiment_labels_project_citation
            UNIQUE (project_id, citation_id);
    END IF;
END $$;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
