"""add yuanbao_search engine protocol

Revision ID: c3d4e5f6a7b8
Revises: b72c8d9e0f11
Create Date: 2026-11-13 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b72c8d9e0f11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONSTRAINT = "engine_protocol"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "ai_engine_entries", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "ai_engine_entries",
        "protocol IN ('openai_compatible', 'yuanbao_search', 'custom')",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "ai_engine_entries", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "ai_engine_entries",
        "protocol IN ('openai_compatible', 'custom')",
    )
