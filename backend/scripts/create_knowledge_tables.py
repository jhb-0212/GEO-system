"""【已退役，勿用于新部署】知识库三张表已进入迁移链 `q3d4e5f6a7b8`；
此脚本只保留给「被它建过表、但 alembic_version 落后」的老开发库做兜底。"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import text

from app.db.session import engine
from app.models import KnowledgeCandidateFact, KnowledgeChunk, KnowledgeDocument


def main() -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    for model in (KnowledgeDocument, KnowledgeChunk, KnowledgeCandidateFact):
        model.__table__.create(engine, checkfirst=True)
        print(f"{model.__tablename__}: ready")
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS embedding_vec vector(1024)")
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding_hnsw "
                "ON knowledge_chunks USING hnsw (embedding_vec vector_cosine_ops) "
                "WITH (m = 16, ef_construction = 64)"
            )
        )
    print("knowledge_chunks.embedding_vec + hnsw: ready")


if __name__ == "__main__":
    main()
