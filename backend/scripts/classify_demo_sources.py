"""把演示项目里 pending 的被引域名批量归类。

只用于 `onbdem` 演练项目。默认归为 `other`，备注明确是合成演练，
不声称做过真实站点判断；目的是验证批量归类接口、引用回填和审计链路。

    backend\\.venv\\Scripts\\python.exe backend\\scripts\\classify_demo_sources.py --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal  # noqa: E402
from app.models import CitationSourceReview, Project  # noqa: E402
from app.models.enums import SourceReviewStatus  # noqa: E402

BASE = "http://127.0.0.1:8000/api/v1"


def _login() -> str:
    response = httpx.post(
        f"{BASE}/auth/login",
        json={"username": "geo_reviewer", "password": "geo-user-dev"},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()["data"]["access_token"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-code", default="onbdem950e9b")
    parser.add_argument("--category", default="other")
    parser.add_argument(
        "--use-suggested",
        action="store_true",
        help="按系统建议分组归类；没有建议的归 other。只做合成演练，不声称人工核站。",
    )
    parser.add_argument(
        "--include-classified",
        action="store_true",
        help="把已 classified 的域名也重新分组归类，用于纠正上一轮粗粒度归类。",
    )
    parser.add_argument(
        "--note",
        default="合成演练：统一归为其他，仅验证批量状态流转与审计；不代表真实站点类别判断",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None or not project.code.startswith("onbdem"):
            print("只允许 onbdem 开头的演练项目", file=sys.stderr)
            return 2
        statuses = [SourceReviewStatus.PENDING]
        if args.include_classified:
            statuses.append(SourceReviewStatus.CLASSIFIED)
        pending = list(
            db.scalars(
                select(CitationSourceReview).where(
                    CitationSourceReview.project_id == project.id,
                    CitationSourceReview.status.in_(statuses),
                )
            ).all()
        )
        project_id = str(project.id)

    print(f"待归类域名：{len(pending)} 个")
    for row in pending[:20]:
        print(f"  - {row.domain}（建议：{row.suggested_source_category.value if row.suggested_source_category else '无'}）")
    if not pending:
        print("没有待处理域名，无需处理。")
        return 0
    if len(pending) > 200:
        raise SystemExit("一次最多 200 个域名，请先分批")
    if not args.apply:
        print("\n[dry-run] 未写入；加 --apply 执行批量归类。")
        return 0

    if args.use_suggested:
        groups: dict[str, list[CitationSourceReview]] = {}
        for row in pending:
            category = row.suggested_source_category.value if row.suggested_source_category else "other"
            groups.setdefault(category, []).append(row)
    else:
        groups = {args.category: pending}

    token = _login()
    for category, rows in sorted(groups.items()):
        response = httpx.post(
            f"{BASE}/projects/{project_id}/citations/source-reviews/bulk-classify",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "review_ids": [str(row.id) for row in rows],
                "source_category": category,
                "review_note": (
                    f"合成演练：按系统建议归为 {category}，未人工核站；仅验证批量归类与审计"
                    if args.use_suggested
                    else args.note
                ),
            },
            timeout=60,
        )
        response.raise_for_status()
        print(f"  {category}: {response.json()['data']}")

    with SessionLocal() as db:
        rows = db.execute(
            select(CitationSourceReview.status, CitationSourceReview.source_category)
            .where(CitationSourceReview.project_id == project.id)
            .order_by(CitationSourceReview.status)
        ).all()
    from collections import Counter

    counts = Counter((status.value, category.value if category else None) for status, category in rows)
    print("归类后分布：")
    for (status, category), count in counts.items():
        print(f"  {status} / {category or '-'}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
