"""add publish account oauth connection binding (idempotent)

Revision ID: t9a0b1c2d3e4
Revises: s3e4f5a6b7c8
Create Date: 2026-11-21

发布账号模型已带 `oauth_connection_id`，但迁移链里缺少对应 DDL；本地库曾被
手工/临时迁移补过该列。本迁移用 `IF NOT EXISTS` 写法，既能给新库补齐，也能
在已有该列的库上安全通过。
"""

from alembic import op

revision = "t9a0b1c2d3e4"
down_revision = "s3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE publish_accounts "
        "ADD COLUMN IF NOT EXISTS oauth_connection_id UUID"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_publish_accounts_oauth_connection_id'
            ) THEN
                ALTER TABLE publish_accounts
                ADD CONSTRAINT fk_publish_accounts_oauth_connection_id
                FOREIGN KEY (oauth_connection_id)
                REFERENCES oauth_connections(id)
                ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_publish_accounts_oauth_connection'
            ) THEN
                ALTER TABLE publish_accounts
                ADD CONSTRAINT uq_publish_accounts_oauth_connection
                UNIQUE (oauth_connection_id);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE publish_accounts "
        "DROP CONSTRAINT IF EXISTS uq_publish_accounts_oauth_connection"
    )
    op.execute(
        "ALTER TABLE publish_accounts "
        "DROP CONSTRAINT IF EXISTS fk_publish_accounts_oauth_connection_id"
    )
    op.execute(
        "ALTER TABLE publish_accounts "
        "DROP COLUMN IF EXISTS oauth_connection_id"
    )
