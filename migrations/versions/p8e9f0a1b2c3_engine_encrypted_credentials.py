"""AI 平台入口密钥改为系统内加密存储

Revision ID: p8e9f0a1b2c3
Revises: p7d8e9f0a1b2

说明：
- 运营要求「在系统里填 Key」，不再每次改 `.env`；
- 密钥不落明文：写入时按 SECRET_KEY 派生 Fernet 密钥加密，密文带 `v1:` 前缀；
- 旧的 `credential_ref`（环境变量名）继续有效，且优先级低于库内密文；
- `encrypted_secret_secondary` 供双密钥协议（腾讯元宝 SecretId + SecretKey）使用；
- `credential_updated_at` 记录密钥最后一次在系统内更新的时间（不记任何值）。
"""

from alembic import op
import sqlalchemy as sa

revision = "p8e9f0a1b2c3"
down_revision = "p7d8e9f0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_engine_entries", sa.Column("encrypted_secret", sa.Text(), nullable=True))
    op.add_column(
        "ai_engine_entries",
        sa.Column("encrypted_secret_secondary", sa.Text(), nullable=True),
    )
    op.add_column(
        "ai_engine_entries",
        sa.Column("credential_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_engine_entries", "credential_updated_at")
    op.drop_column("ai_engine_entries", "encrypted_secret_secondary")
    op.drop_column("ai_engine_entries", "encrypted_secret")
