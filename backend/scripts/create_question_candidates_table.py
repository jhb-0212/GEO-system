"""幂等创建问题候选池表；当前仓库没有 Alembic 版本链，开发库用此脚本补齐。"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import engine
from app.models import QuestionCandidate


def main() -> None:
    QuestionCandidate.__table__.create(engine, checkfirst=True)
    print("question_candidates: ready")


if __name__ == "__main__":
    main()
