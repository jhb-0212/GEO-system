"""重置演练项目的监测数据，保留题目、品牌、竞品与客户配置。

用途：演示/测试反复重跑基线、复测、SoV、FAQ 验证；真实项目（如 gz-base）
默认拒绝。只允许编码以 `onbdem` 开头的演练项目。

    backend\\.venv\\Scripts\\python.exe backend\\scripts\\reset_demo_project.py --project-code onbdem950e9b
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models import Project  # noqa: E402
from app.services.demo_reset import reset_project_monitoring  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-code", required=True)
    parser.add_argument("--allow-non-demo", action="store_true")
    parser.add_argument("--drop-retest-plans", action="store_true", default=False)
    parser.add_argument("--dry-run", action="store_true", default=False)
    args = parser.parse_args()

    if not args.project_code.startswith("onbdem") and not args.allow_non_demo:
        raise SystemExit("拒绝清理非演练项目；确需执行请加 --allow-non-demo")

    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None:
            raise SystemExit(f"项目不存在：{args.project_code}")
        counts = reset_project_monitoring(
            db,
            project.id,
            drop_retest_plans=args.drop_retest_plans,
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            db.commit()
        print(
            json.dumps(
                {
                    "project": project.code,
                    "dry_run": args.dry_run,
                    "would_delete" if args.dry_run else "deleted": counts,
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
