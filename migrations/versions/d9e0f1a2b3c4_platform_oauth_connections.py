"""平台 OAuth 授权：连接与一次性 state

Revision ID: d9e0f1a2b3c4
Revises: c5d6e7f8a9b0
Create Date: 2026-11-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONNECTION_STATUSES = ("connected", "revoked", "error")


def upgrade() -> None:
    op.create_table(
        "oauth_connections",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("channel_id", sa.Uuid(), nullable=True),
        sa.Column("provider_code", sa.String(length=64), nullable=False),
        sa.Column("external_account_id", sa.String(length=255), nullable=False),
        sa.Column("external_account_name", sa.String(length=255), nullable=True),
        sa.Column("external_account_email", sa.String(length=255), nullable=True),
        sa.Column(
            "scopes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                *CONNECTION_STATUSES,
                name="oauth_connection_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="connected",
            nullable=False,
        ),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("token_type", sa.String(length=32), server_default="Bearer", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_by", sa.Uuid(), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["channels.id"],
            name=op.f("fk_oauth_connections_channel_id_channels"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["connected_by"],
            ["users.id"],
            name=op.f("fk_oauth_connections_connected_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_oauth_connections_project_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_connections")),
        sa.UniqueConstraint(
            "project_id",
            "provider_code",
            "external_account_id",
            name="uq_oauth_connections_project_provider_external",
        ),
    )
    op.create_index(
        "ix_oauth_connections_project_provider",
        "oauth_connections",
        ["project_id", "provider_code"],
        unique=False,
    )
    op.create_index(
        "ix_oauth_connections_channel",
        "oauth_connections",
        ["channel_id"],
        unique=False,
    )

    op.create_table(
        "oauth_authorization_states",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("provider_code", sa.String(length=64), nullable=False),
        sa.Column("channel_id", sa.Uuid(), nullable=True),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("code_verifier_encrypted", sa.Text(), nullable=False),
        sa.Column("redirect_uri", sa.String(length=2048), nullable=False),
        sa.Column("return_path", sa.String(length=512), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["channels.id"],
            name=op.f("fk_oauth_authorization_states_channel_id_channels"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_oauth_authorization_states_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_oauth_authorization_states_project_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_authorization_states")),
        sa.UniqueConstraint("state_hash", name="uq_oauth_authorization_states_state_hash"),
    )
    op.create_index(
        "ix_oauth_authorization_states_expiry",
        "oauth_authorization_states",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_oauth_authorization_states_expiry", table_name="oauth_authorization_states")
    op.drop_table("oauth_authorization_states")
    op.drop_index("ix_oauth_connections_channel", table_name="oauth_connections")
    op.drop_index("ix_oauth_connections_project_provider", table_name="oauth_connections")
    op.drop_table("oauth_connections")
