"""Revision ID: f2b3c4d5e6a7
Revises: e1a2b3c4d5f6
Create Date: 2026-11-24

客户主体 + 行业预设 + 项目策略。一次加法迁移：
③ 建 organizations / industry_presets / project_strategies
④ projects.organization_id（nullable → 回填 → NOT NULL）
不改 projects.code 唯一约束，不动成员表与 78 张业务表。
"""

import json
import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f2b3c4d5e6a7"
down_revision = "e1a2b3c4d5f6"
branch_labels = None
depends_on = None

PRESET_PATH = Path(__file__).resolve().parents[2] / "seed_data" / "industry_presets" / "edu-training.json"


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("branding", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "industry_presets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("config", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "project_strategies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("strategy_key", sa.String(length=64), nullable=False),
        sa.Column("config", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "strategy_key", "version", name="uq_project_strategies_key_version"),
    )
    op.create_index("ix_project_strategies_project_key", "project_strategies", ["project_id", "strategy_key"])

    op.add_column("projects", sa.Column("organization_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_projects_organization_id_organizations",
        "projects", "organizations", ["organization_id"], ["id"], ondelete="RESTRICT",
    )

    # 回填：一个默认客户 org；现有项目全部挂上去；每个项目一条 industry 策略（继承预设）
    conn = op.get_bind()
    org_id = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO organizations (id, code, name, status, branding) "
            "VALUES (:id, 'default-client', '默认客户', 'active', '{}'::jsonb)"
        ),
        {"id": org_id},
    )
    conn.execute(sa.text("UPDATE projects SET organization_id = :org WHERE organization_id IS NULL"), {"org": org_id})
    op.alter_column("projects", "organization_id", nullable=False)

    preset = json.loads(PRESET_PATH.read_text(encoding="utf-8"))
    conn.execute(
        sa.text("INSERT INTO industry_presets (id, code, name, config) VALUES (:id, :code, :name, :config)"),
        {
            "id": uuid.uuid4(),
            "code": preset["code"],
            "name": preset.get("name", preset["code"]),
            "config": json.dumps(preset, ensure_ascii=False),
        },
    )
    conn.execute(
        sa.text(
            "INSERT INTO project_strategies (id, project_id, strategy_key, config, version, status) "
            "SELECT gen_random_uuid(), p.id, 'industry', :config, 1, 'active' FROM projects p "
            "WHERE NOT EXISTS (SELECT 1 FROM project_strategies s WHERE s.project_id = p.id AND s.strategy_key = 'industry')"
        ),
        {"config": json.dumps({"preset_code": preset["code"], "overrides": {}}, ensure_ascii=False)},
    )


def downgrade() -> None:
    op.drop_constraint("fk_projects_organization_id_organizations", "projects", type_="foreignkey")
    op.drop_column("projects", "organization_id")
    op.drop_index("ix_project_strategies_project_key", table_name="project_strategies")
    op.drop_table("project_strategies")
    op.drop_table("industry_presets")
    op.drop_table("organizations")
