"""官网诊断与访问观测：L1 页面检查字段、L2 爬虫事件、L3 用户访问事件。

Revision ID: a9b0c1d2e3f4
Revises: z8e9f0a1b2c3
Create Date: 2026-11-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9b0c1d2e3f4"
down_revision: Union[str, None] = "z8e9f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # L1：页面技术可访问性检查结果
    op.add_column("public_pages", sa.Column("robots_allowed", sa.Boolean(), nullable=True))
    op.add_column("public_pages", sa.Column("in_sitemap", sa.Boolean(), nullable=True))
    op.add_column("public_pages", sa.Column("canonical_ok", sa.Boolean(), nullable=True))
    op.add_column("public_pages", sa.Column("http_status", sa.Integer(), nullable=True))
    op.add_column("public_pages", sa.Column("js_dependent", sa.Boolean(), nullable=True))
    op.add_column("public_pages", sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("public_pages", sa.Column("check_error", sa.Text(), nullable=True))

    # L2：官网/CDN 访问日志导入的爬虫请求
    op.create_table(
        "crawler_events",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("public_page_id", sa.Uuid(), nullable=True),
        sa.Column("page_url", sa.Text(), nullable=False),
        sa.Column("ua_claimed", sa.String(length=512), nullable=True),
        sa.Column("source_ip", sa.String(length=64), nullable=True),
        sa.Column("verified_bot", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("bytes", sa.BigInteger(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("import_source", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"],
            name=op.f("fk_crawler_events_project_id_projects"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["public_page_id"], ["public_pages.id"],
            name=op.f("fk_crawler_events_public_page_id_public_pages"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_crawler_events")),
    )
    op.create_index(
        "ix_crawler_events_project_occurred",
        "crawler_events",
        ["project_id", "occurred_at"],
    )
    op.create_index(
        "ix_crawler_events_project_bot",
        "crawler_events",
        ["project_id", "verified_bot"],
    )

    # L3：官网埋点/日志导入的用户访问事件
    op.create_table(
        "traffic_events",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("visitor_session_id", sa.String(length=64), nullable=True),
        sa.Column("landing_url", sa.Text(), nullable=False),
        sa.Column("utm_source", sa.String(length=128), nullable=True),
        sa.Column("utm_campaign", sa.String(length=128), nullable=True),
        sa.Column("referrer", sa.Text(), nullable=True),
        sa.Column("is_bot", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("import_source", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"],
            name=op.f("fk_traffic_events_project_id_projects"), ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_traffic_events")),
    )
    op.create_index(
        "ix_traffic_events_project_occurred",
        "traffic_events",
        ["project_id", "occurred_at"],
    )
    op.create_index(
        "ix_traffic_events_project_session",
        "traffic_events",
        ["project_id", "visitor_session_id"],
    )

    # leads 通过匿名 session 与 traffic_events 关联
    op.add_column("leads", sa.Column("session_id", sa.String(length=64), nullable=True))
    op.create_index("ix_leads_project_session", "leads", ["project_id", "session_id"])


def downgrade() -> None:
    op.drop_index("ix_leads_project_session", table_name="leads")
    op.drop_column("leads", "session_id")
    op.drop_index("ix_traffic_events_project_session", table_name="traffic_events")
    op.drop_index("ix_traffic_events_project_occurred", table_name="traffic_events")
    op.drop_table("traffic_events")
    op.drop_index("ix_crawler_events_project_bot", table_name="crawler_events")
    op.drop_index("ix_crawler_events_project_occurred", table_name="crawler_events")
    op.drop_table("crawler_events")
    op.drop_column("public_pages", "check_error")
    op.drop_column("public_pages", "checked_at")
    op.drop_column("public_pages", "js_dependent")
    op.drop_column("public_pages", "http_status")
    op.drop_column("public_pages", "canonical_ok")
    op.drop_column("public_pages", "in_sitemap")
    op.drop_column("public_pages", "robots_allowed")
