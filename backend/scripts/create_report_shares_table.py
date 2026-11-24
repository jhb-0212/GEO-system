"""【已退役，勿用于新部署】月报分享表已进入迁移链 `q3d4e5f6a7b8`；此脚本只给老开发库兜底。"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import engine
from app.models import ReportShare


def main() -> None:
    ReportShare.__table__.create(engine, checkfirst=True)
    print("report_shares: ready")


if __name__ == "__main__":
    main()
