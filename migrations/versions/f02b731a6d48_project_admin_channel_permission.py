"""Backfill project admin channel.write in existing seeded databases.

Revision ID: f02b731a6d48
Revises: e91a4c7d230b
"""

import uuid

from alembic import op
import sqlalchemy as sa


revision = "f02b731a6d48"
down_revision = "e91a4c7d230b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(sa.text("""
        INSERT INTO role_permissions (id, role_id, permission_id)
        SELECT :mapping_id, roles.id, permissions.id
        FROM roles CROSS JOIN permissions
        WHERE roles.code = 'project_admin' AND permissions.code = 'channel.write'
        ON CONFLICT (role_id, permission_id) DO NOTHING
    """), {"mapping_id": uuid.uuid4()})


def downgrade() -> None:
    # Existing databases may already have this mapping; do not revoke it on downgrade.
    pass
