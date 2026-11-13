"""add unique baseline round per project

Revision ID: 882cf6d84462
Revises: 32e8750970c2
Create Date: 2026-11-12 16:33:07.206401

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '882cf6d84462'
down_revision: Union[str, None] = '32e8750970c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_monitoring_rounds_project_baseline",
        "monitoring_rounds",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("is_baseline IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_monitoring_rounds_project_baseline",
        table_name="monitoring_rounds",
    )
