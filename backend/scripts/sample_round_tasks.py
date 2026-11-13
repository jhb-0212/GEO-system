"""CLI 采样器：把指定项目/轮次的 pending 任务跑完，落失败样本并回写终态。

用法（在 backend 目录下）：
    .venv\\Scripts\\python.exe scripts\\sample_round_tasks.py --project-code gz-base
    .venv\\Scripts\\python.exe scripts\\sample_round_tasks.py --project-code gz-base --round-id <uuid>
    .venv\\Scripts\\python.exe scripts\\sample_round_tasks.py --project-code gz-base --json

本期为技术链路基线：无可用入口/凭据，样本如实落 `access_blocked`，不伪造命中。
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models import Project  # noqa: E402
from app.services.monitoring_sampler import run_pending_tasks  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="跑完指定项目/轮次的 pending 监测任务")
    parser.add_argument("--project-code", default="gz-base")
    parser.add_argument("--round-id", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    round_id: uuid.UUID | None = None
    if args.round_id:
        try:
            round_id = uuid.UUID(args.round_id)
        except ValueError:
            print("--round-id 不是合法 UUID", file=sys.stderr)
            return 2
    session = SessionLocal()
    try:
        project = session.scalar(select(Project).where(Project.code == args.project_code))
        if project is None:
            print(f"找不到项目 code={args.project_code}", file=sys.stderr)
            return 2
        result = run_pending_tasks(session, project_id=project.id, round_id=round_id)
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
            f"项目 {args.project_code}：pending {result['pending_task_count']} 条，"
            f"落失败样本 {result['failed_task_count']} 条"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
