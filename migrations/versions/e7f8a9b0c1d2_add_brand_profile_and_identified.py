"""品牌实体配置表 + 样本 brand_identified 字段 + 品牌口径维护权限回填

Revision ID: e7f8a9b0c1d2
Revises: d5e6f7a8b9c0
Create Date: 2026-11-17

三件事一次做完：
1. 建 `brand_profiles`：正式名 / 别名 / 唯一标识 / 自有域名，一个项目一份；
2. 给 `monitoring_samples` 加 `brand_identified`：与 `brand_mentioned` 并行、
   互不覆盖，保证历史提及率口径不变、可跨期比较；
3. 回填 `brand.manage` 能力码与角色映射（已有库由 seed 之外的路径补齐，
   避免升级后接口 403）。

注意 downgrade 的行为：
- 表与列直接删（结构变更可逆）；
- 权限码采取“只增不删”，与 `f02b731a6d48` 保持一致——已有库可能已有人工授予，
  降级时回收会静默收走别人的权限。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brand_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_name", sa.String(length=255), nullable=False),
        sa.Column("aliases", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("identifiers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("owned_domains", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_brand_profiles_project_id_projects",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_brand_profiles"),
        sa.UniqueConstraint("project_id", name="uq_brand_profiles_project"),
    )
    op.create_index(
        "ix_brand_profiles_project_active", "brand_profiles", ["project_id", "is_active"]
    )

    op.add_column(
        "monitoring_samples",
        sa.Column("brand_identified", sa.Boolean(), nullable=True),
    )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO permissions (id, code, name, scope, description)
            VALUES (gen_random_uuid(), 'brand.manage', '维护品牌口径', 'project',
                    '配置品牌正式名、别名、唯一标识与自有域名')
            ON CONFLICT (code) DO NOTHING
            """
        )
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO role_permissions (id, role_id, permission_id)
            SELECT gen_random_uuid(), roles.id, permissions.id
            FROM roles CROSS JOIN permissions
            WHERE roles.code IN ('project_admin', 'editor') AND permissions.code = 'brand.manage'
            ON CONFLICT (role_id, permission_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_column("monitoring_samples", "brand_identified")
    op.drop_index("ix_brand_profiles_project_active", table_name="brand_profiles")
    op.drop_table("brand_profiles")
    # 权限码只增不删：降级不回收集，见模块说明。
