"""审计项目内每个监测样本是否至少有一个证据文件。

用法：
  python scripts/audit_sample_evidence.py
  python scripts/audit_sample_evidence.py --project gz-base
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal  # noqa: E402
from app.models import Project  # noqa: E402
from app.services.sample_evidence import evidence_coverage  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, help="项目 code 或 UUID，必须显式指定")
    args = parser.parse_args()

    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == args.project))
        if project is None:
            try:
                project = db.scalar(
                    select(Project).where(Project.id == uuid.UUID(args.project))
                )
            except ValueError:
                project = None
        if project is None:
            raise SystemExit(f"项目不存在：{args.project}")

        coverage = evidence_coverage(db, project.id)
        print(json.dumps({"project": project.code, **coverage}, ensure_ascii=False, indent=2))
        raise SystemExit(0 if coverage["samples_missing_evidence"] == 0 else 1)


if __name__ == "__main__":
    main()
