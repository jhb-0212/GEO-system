"""Associate target keywords with project questions.

Revision ID: e91a4c7d230b
Revises: b72c8d9e0f11
"""

from alembic import op
import sqlalchemy as sa


revision = "e91a4c7d230b"
down_revision = "b72c8d9e0f11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "question_keywords",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("keyword_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["keyword_id"], ["keywords.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("question_id", "keyword_id", name="uq_question_keywords_question_keyword"),
    )
    op.create_index("ix_question_keywords_project", "question_keywords", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_question_keywords_project", table_name="question_keywords")
    op.drop_table("question_keywords")
