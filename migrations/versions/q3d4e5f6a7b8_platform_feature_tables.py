"""补齐 12 张只在脚本里建过的表，让 `alembic upgrade head` 能建出完整新库。

Revision ID: q3d4e5f6a7b8
Revises: p2c3d4e5f6a7
Create Date: 2026-11-24

背景：知识库、预警、只读 API Key、报告分享、线索归因、媒体渠道适配、机会建议、
候选问句这些头部能力上线时，是拿 `backend/scripts/create_*_tables.py` 直接
CREATE TABLE 建出来的，没有进版本链。后果很具体：

- 新部署（含给新客户开库）跑完 `alembic upgrade head` 会缺这 12 张表，
  知识库、预警、只读 API、报告分享、线索归因整条链路直接 500；
- 开发库与生产库的表结构靠"谁跑过脚本"决定，升级顺序无法复现。

这个迁移只负责把这些表纳入版本链。结构以 `app/models` 为唯一真源：将来要改列，
新增迁移，不要改这一份——否则前后两次全新部署会建出不同结构。

知识库切块检索依赖 Postgres vector 扩展（`knowledge_chunks.embedding_vec` 与
HNSW 索引）。没有扩展权限时这里不静默跳过：`CREATE EXTENSION` 失败会直接抛错，
因为少了扩展，知识库检索这一层等于不可用，应该尽早暴露而不是延迟到线上查询。
"""

import app.models  # noqa: F401  注册所有模型到 Base.metadata
from alembic import op
from sqlalchemy import text

from app.db.base import Base

revision = "q3d4e5f6a7b8"
down_revision = "p2c3d4e5f6a7"

TABLES = (
    "knowledge_documents",
    "knowledge_chunks",
    "knowledge_candidate_facts",
    "alert_rules",
    "alert_events",
    "api_keys",
    "report_shares",
    "lead_attributions",
    "media_providers",
    "media_orders",
    "opportunity_suggestions",
    "question_candidates",
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    for name in TABLES:
        # 已由建表脚本创建过的开发库：checkfirst 跳过，迁移只补记版本
        Base.metadata.tables[name].create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for name in reversed(TABLES):
        Base.metadata.tables[name].drop(bind, checkfirst=True)
