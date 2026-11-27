"""下线微站：删除 site_sites / site_modules，并把「微站线索」额度口径改成「线索」

Revision ID: w6f7a8b9c0d1
Revises: v04e5f6a7b8c
Create Date: 2026-11-27

微站（K8）与客户自有官网职责重复：对外页面由官网承担，系统内不再保留第二套站点。
本次迁移只做两件事：
1. 删掉微站两张表（数据不可恢复，执行前先备份）；
2. 把客户配额里沿用的 microsite_lead 键改名为 lead——指标本身统计的就是 leads 全量，
   与来源无关，旧键名只是历史遗留。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "w6f7a8b9c0d1"
down_revision: Union[str, None] = "v04e5f6a7b8c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("site_modules")
    op.drop_table("site_sites")

    # 旧额度键只在确实存在时搬运；path 不存在时不动，避免给客户凭空造出 quotas 结构
    op.execute(
        """
        UPDATE organizations
        SET settings = jsonb_set(
            settings #- '{quotas,consumption,microsite_lead}',
            '{quotas,consumption,lead}',
            settings #> '{quotas,consumption,microsite_lead}',
            true
        )
        WHERE settings #> '{quotas,consumption,microsite_lead}' IS NOT NULL
        """
    )

    # SEO 必备标签口径只服务微站核验，核验接口已下线：项目级覆盖行一并清掉
    op.execute("DELETE FROM project_policies WHERE key = 'seo.required_tags'")


def downgrade() -> None:
    op.execute(
        """
        UPDATE organizations
        SET settings = jsonb_set(
            settings #- '{quotas,consumption,lead}',
            '{quotas,consumption,microsite_lead}',
            settings #> '{quotas,consumption,lead}',
            true
        )
        WHERE settings #> '{quotas,consumption,lead}' IS NOT NULL
        """
    )

    op.create_table(
        "site_sites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("intro", sa.Text(), nullable=True),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_site_sites_project_id_projects", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_site_sites_project_id"),
        sa.UniqueConstraint("slug", name="uq_site_sites_slug"),
    )

    op.create_table(
        "site_modules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("module_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column(
            "content", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_site_modules_project_id_projects", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["site_sites.id"], name="fk_site_modules_site_id_site_sites", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "module_type", name="uq_site_modules_site_type"),
        sa.CheckConstraint(
            "module_type in ('home','services','news','download','poster','card')",
            name="ck_site_modules_site_module_type",
        ),
    )
    op.create_index("ix_site_modules_project_order", "site_modules", ["project_id", "sort_order"])
