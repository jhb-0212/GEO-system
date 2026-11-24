"""幂等补齐头部能力新增表/列（P1-6 至 P2）。

【已退役，勿用于新部署】新表已进入迁移链 `q3d4e5f6a7b8`；
此脚本只保留给老开发库兜底，只做 CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS，
不修改已有业务数据。运行前先确保 Postgres 镜像带 vector 扩展。
"""

import sys
from pathlib import Path

from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.base import Base
from app.db.session import engine
import app.models  # noqa: F401  注册所有模型


def main() -> None:
    Base.metadata.create_all(engine, checkfirst=True)
    statements = [
        "ALTER TABLE monitoring_samples ADD COLUMN IF NOT EXISTS brand_recommendation boolean",
        "ALTER TABLE monitoring_samples ADD COLUMN IF NOT EXISTS recommendation_reason varchar(64)",
        "ALTER TABLE monitoring_samples ADD COLUMN IF NOT EXISTS entity_mention_count integer",
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
    print("head feature tables/columns: ready")


if __name__ == "__main__":
    main()
