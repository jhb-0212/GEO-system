"""merge heads: publish_visibility + remove_deepseek_websearch

Revision ID: h8f9a0b1c2d3
Revises: ea55a9ad6c5d, g7e8f9a0b1c2
Create Date: 2026-11-17 16:25:00
"""

from typing import Sequence, Union

revision: str = "h8f9a0b1c2d3"
down_revision: Union[str, Sequence[str], None] = ("ea55a9ad6c5d", "g7e8f9a0b1c2")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
