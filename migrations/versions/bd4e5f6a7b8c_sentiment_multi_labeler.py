"""情感抽样盲评：允许同一引用被多个标注人独立标注。

Revision ID: bd4e5f6a7b8c
Revises: ab2c3d4e5f7
Create Date: 2026-11-24

原唯一约束把「一条引用只能有一个情感结论」写死了，双人盲评无法落库。
改为 (project_id, citation_id, labeled_by) 唯一：同一人同一引用仍只能标一次，
不同标注人可以各写各的；分歧由服务层仲裁，不在库里强行合并。
"""

from typing import Sequence, Union

from alembic import op

revision: str = "bd4e5f6a7b8c"
down_revision: Union[str, None] = "ab2c3d4e5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_sentiment_labels_project_citation", "sentiment_labels", type_="unique"
    )
    op.create_unique_constraint(
        "uq_sentiment_labels_project_citation_labeler",
        "sentiment_labels",
        ["project_id", "citation_id", "labeled_by"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_sentiment_labels_project_citation_labeler", "sentiment_labels", type_="unique"
    )
    op.create_unique_constraint(
        "uq_sentiment_labels_project_citation",
        "sentiment_labels",
        ["project_id", "citation_id"],
    )
