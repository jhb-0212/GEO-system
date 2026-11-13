"""激活首期 6 题的技术基线 v2（1 道品牌题 + 5 道通用题）。

用法（在 backend 目录下）：
    .venv\\Scripts\\python.exe scripts\\activate_baseline_questions.py --project-code gz-base
    .venv\\Scripts\\python.exe scripts\\activate_baseline_questions.py --project-code gz-base --dry-run --json

口径：active = 进入监测，不等于运营定稿；旧占位 v1 保留，运营确认后追加 v3。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal  # noqa: E402
from app.services.question_baseline import activate_technical_baseline  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="激活 6 题技术基线")
    parser.add_argument("--project-code", default="gz-base")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        result = activate_technical_baseline(
            session,
            args.project_code,
            dry_run=args.dry_run,
        )
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"{result['project_code']} / {result['baseline']}："
            f"激活 {result['activated']} 题，新建版本 {result['created_versions']}，"
            f"已激活 {result['already_active']} 题，dry_run={result['dry_run']}"
        )
        for row in result["questions"]:
            created = "新建 v" if row["version_created"] else "沿用 v"
            print(f"  {row['code']} [{row['question_type']}] {created}{row['version_no']} {row['text']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
