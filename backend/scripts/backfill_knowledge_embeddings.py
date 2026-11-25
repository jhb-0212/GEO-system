"""为已有知识库切块补写 embedding（bge-m3 到位后的一次性回填）。"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import KnowledgeChunk
from app.services import knowledge_embedding


def main() -> None:
    with SessionLocal() as db:
        rows = db.scalars(select(KnowledgeChunk).where(
            KnowledgeChunk.embedding_vec.is_(None)
        ).order_by(KnowledgeChunk.created_at)).all()
        print(f"chunks without embedding: {len(rows)}")
        if not rows:
            return
        model = knowledge_embedding.embedding_model()
        for start in range(0, len(rows), 16):
            batch = rows[start:start + 16]
            vectors = knowledge_embedding.embed_texts([row.text for row in batch])
            if not vectors:
                print("embedding service unavailable; nothing written")
                return
            for row, vector in zip(batch, vectors):
                row.embedding = vector
                row.embedding_vec = vector
                row.embedding_model = model
            db.commit()
            print(f"embedded {start + len(batch)}/{len(rows)}")
    print("knowledge chunk embeddings: ready")


if __name__ == "__main__":
    main()
