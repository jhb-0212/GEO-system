"""内部 GEO 验收报告（CLI）：输出有效回答、提及率、引用份额、SOV、题库覆盖、新鲜度、失败率。

用法（backend 目录）：
    .venv\\Scripts\\python.exe scripts\\geo_report.py --project-code gz-base
    .venv\\Scripts\\python.exe scripts\\geo_report.py --project-code gz-base --json
退出码：
    0 正常输出；2 指定 --require-valid-answers 但有效回答为 0。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal  # noqa: E402
from app.models import MonitoringRound, Project  # noqa: E402
from app.services.stats import geo_overview  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="GEO 内部验收指标")
    parser.add_argument("--project-code", required=True, help="项目 code，如 gz-base")
    parser.add_argument("--round-seq", type=int, default=None, help="只统计指定轮次 seq")
    parser.add_argument("--json", action="store_true", help="只输出 JSON")
    parser.add_argument(
        "--require-valid-answers",
        action="store_true",
        help="有效回答为 0 时以退出码 2 结束，避免把技术链路基线当成业务基线",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None:
            print(f"项目不存在：{args.project_code}", file=sys.stderr)
            return 1
        round_id = None
        if args.round_seq is not None:
            round_row = db.scalar(
                select(MonitoringRound).where(
                    MonitoringRound.project_id == project.id,
                    MonitoringRound.seq == args.round_seq,
                )
            )
            if round_row is None:
                print(f"轮次不存在：seq={args.round_seq}", file=sys.stderr)
                return 1
            round_id = round_row.id
        report = geo_overview(db, project.id, round_id=round_id)

    output = {
        "project_code": args.project_code,
        "round_seq": args.round_seq,
        **report,
    }
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"项目：{args.project_code}")
        print(f"结论：{report['statement']}")
        print(f"有效回答：{report['valid_answers']}")
        for key in ("mention_rate", "citation_share", "sov", "prompt_coverage", "freshness_hours", "fresh_24h_rate", "failure_rate"):
            value = report[key]
            print(f"{key}: {'N/A' if value is None else value}")
        print("计数：", json.dumps(report["counts"], ensure_ascii=False))
        if report["by_competitor"]:
            print("竞品 SOV 计数：", json.dumps(report["by_competitor"], ensure_ascii=False))

    if args.require_valid_answers and report["valid_answers"] == 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
