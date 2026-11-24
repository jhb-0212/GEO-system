"""把演示项目里仍为 auto 的引用逐条人工确认。

只用于 `onbdem` 演练项目；备注明确写明“假引擎轮/合成引用”，不把自动状态
当成人工确认，也不修改引用 URL 或渠道归属。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx
from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal  # noqa: E402
from app.models import MonitoringCitation, Project  # noqa: E402
from app.models.enums import CitationReviewStatus  # noqa: E402

BASE = "http://127.0.0.1:8000/api/v1"


def _login(username: str, password: str) -> str:
    response = httpx.post(f"{BASE}/auth/login", json={"username": username, "password": password}, timeout=20)
    response.raise_for_status()
    return response.json()["data"]["access_token"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-code", default="onbdem950e9b")
    parser.add_argument("--operator", default="geo_reviewer")
    parser.add_argument("--batch", type=int, default=100)
    parser.add_argument(
        "--note",
        default="合成演练：假引擎轮引用，人工逐条确认；非真实平台引用",
        help="写入每条引用的确认备注，按实际轮次来源写清楚",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None or not project.code.startswith("onbdem"):
            print("只允许 onbdem 开头的演练项目", file=sys.stderr)
            return 2
        before = db.scalar(
            select(func.count()).select_from(MonitoringCitation).where(
                MonitoringCitation.project_id == project.id,
                MonitoringCitation.review_status == CitationReviewStatus.AUTO,
            )
        ) or 0
        confirmed = db.scalar(
            select(func.count()).select_from(MonitoringCitation).where(
                MonitoringCitation.project_id == project.id,
                MonitoringCitation.review_status == CitationReviewStatus.MANUAL_CONFIRMED,
            )
        ) or 0
        project_id = str(project.id)

    print(f"before auto={before} confirmed={confirmed}")
    token = _login(args.operator, "geo-user-dev")
    headers = {"Authorization": f"Bearer {token}"}
    updated = 0
    while True:
        response = httpx.get(
            f"{BASE}/projects/{project_id}/citations",
            params={"review_status": "auto", "page": 1, "page_size": args.batch},
            headers=headers,
            timeout=60,
        )
        response.raise_for_status()
        rows = response.json()["data"]
        if not rows:
            break
        for row in rows:
            patch = httpx.patch(
                f"{BASE}/projects/{project_id}/citations/{row['citation_id']}",
                headers=headers,
                json={
                    "review_status": "manual_confirmed",
                    "review_note": args.note,
                },
                timeout=30,
            )
            if patch.status_code >= 400:
                raise RuntimeError(f"confirm failed {row['citation_id']}: {patch.status_code} {patch.text[:200]}")
            updated += 1
        print(f"confirmed {updated}")

    with SessionLocal() as db:
        db.expire_all()
        auto_after = db.scalar(
            select(func.count()).select_from(MonitoringCitation).where(
                MonitoringCitation.project_id == project.id,
                MonitoringCitation.review_status == CitationReviewStatus.AUTO,
            )
        ) or 0
        confirmed_after = db.scalar(
            select(func.count()).select_from(MonitoringCitation).where(
                MonitoringCitation.project_id == project.id,
                MonitoringCitation.review_status == CitationReviewStatus.MANUAL_CONFIRMED,
            )
        ) or 0
        total = db.scalar(
            select(func.count()).select_from(MonitoringCitation).where(
                MonitoringCitation.project_id == project.id
            )
        ) or 0
    print(f"after auto={auto_after} confirmed={confirmed_after} total={total} updated={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
