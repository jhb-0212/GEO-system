"""merge frontend question_keywords and yuanbao heads

Revision ID: 2fbc5b97e953
Revises: c3d4e5f6a7b8, f02b731a6d48
Create Date: 2026-11-16 09:42:42.797240

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2fbc5b97e953'
down_revision: Union[str, None] = ('c3d4e5f6a7b8', 'f02b731a6d48')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
