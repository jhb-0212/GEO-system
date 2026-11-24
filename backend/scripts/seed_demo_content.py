"""给演示项目补一条模拟内容稿、内容关联和一条排期。

只用于 `onbdem` 演练项目：
- 新建（或复用）固定标题的 mock 母稿与版本；
- 把「广州 AI 实训费用」「AIGC 实训周期」挂到该版本；
- 给版本挂 Q06、Q02 和两条已确认引用；
- 建一条 scheduled 排期。
正文与备注都带「合成演练」，不冒充真实发布内容。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Channel,
    ContentItem,
    ContentPlan,
    ContentVersion,
    Keyword,
    MonitoringCitation,
    Project,
    Question,
)
from app.models.enums import CitationReviewStatus  # noqa: E402

BASE = "http://127.0.0.1:8000/api/v1"
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
TITLE = "合成演练：广州 AI 实训费用与周期说明"
PLAN_TITLE = "合成演练排期：广州 AI 实训费用说明"
BODY = (
    "合成演练内容，非真实发布稿。广州 AI 实训的费用通常由课程模块、实训周期和项目服务决定。"
    "以广州示例数字实训基地为例，线下 AIGC 实训按周期分班，具体费用需要咨询确认；"
    "AIGC 实训周期通常为 8–12 周，包含工具课、项目实战和作品集辅导。"
    "本文用于验证目标词、题目、证据引用和运营排期的关联链路，不构成真实招生或报价信息。"
)


def call(method: str, path: str, token: str | None = None, body: dict | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = httpx.request(method, f"{BASE}{path}", json=body, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def login(username: str, password: str) -> str:
    return call("POST", "/auth/login", body={"username": username, "password": password})["data"]["access_token"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-code", default="onbdem950e9b")
    args = parser.parse_args()

    token = login("geo_editor", "geo-user-dev")

    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None or not project.code.startswith("onbdem"):
            print("只允许 onbdem 开头的演练项目", file=sys.stderr)
            return 2
        project_id = str(project.id)

        item = db.scalar(
            select(ContentItem).where(
                ContentItem.project_id == project.id, ContentItem.title == TITLE
            )
        )
        if item is not None and item.current_version_id:
            version = db.get(ContentVersion, item.current_version_id)
        else:
            version = None

        question_ids = list(
            db.scalars(
                select(Question.id)
                .where(Question.project_id == project.id, Question.code.in_(("Q06", "Q02")))
                .order_by(Question.code)
            ).all()
        )
        citation_ids = list(
            db.scalars(
                select(MonitoringCitation.id)
                .where(
                    MonitoringCitation.project_id == project.id,
                    MonitoringCitation.review_status == CitationReviewStatus.MANUAL_CONFIRMED,
                )
                .order_by(MonitoringCitation.domain, MonitoringCitation.raw_url)
                .limit(2)
            ).all()
        )
        keyword_rows = list(
            db.scalars(
                select(Keyword).where(
                    Keyword.project_id == project.id,
                    Keyword.name.in_(("广州 AI 实训费用", "AIGC 实训周期")),
                )
            ).all()
        )
        channel_id = db.scalar(
            select(Channel.id).where(Channel.project_id == project.id, Channel.code == "wechat-mp")
        )
        plan_exists = db.scalar(
            select(ContentPlan.id).where(
                ContentPlan.project_id == project.id, ContentPlan.title == PLAN_TITLE
            )
        )
        item_id = str(item.id) if item else None
        plan_id = str(plan_exists) if plan_exists else None

    if item is None:
        created = call(
            "POST",
            f"/projects/{project_id}/contents",
            token,
            {"title": TITLE, "kind": "master"},
        )["data"]
        item_id = created["item_id"]
        print(f"创建 mock 母稿：{item_id}")

    if version is None:
        created = call(
            "POST",
            f"/projects/{project_id}/contents/{item_id}/versions",
            token,
            {"body": BODY, "change_note": "合成演练：用于内容关联与排期验证"},
        )["data"]
        version_id = created["version_id"]
        print(f"创建 mock 版本：{version_id}")
        with SessionLocal() as db:
            version = db.get(ContentVersion, version_id)
    else:
        version_id = str(version.id)
        print(f"复用 mock 版本：{version_id}")

    for keyword in keyword_rows:
        payload = call("GET", f"/projects/{project_id}/keywords?page_size=100", token)["data"]
        row = next((r for r in payload if r["name"] == keyword.name), None)
        if row is None:
            raise SystemExit(f"目标词未出现在接口里：{keyword.name}")
        version_ids = sorted({str(v) for v in row.get("content_version_ids", [])} | {version_id})
        call(
            "PATCH",
            f"/projects/{project_id}/keywords/{row['id']}",
            token,
            {"content_version_ids": version_ids},
        )
        print(f"目标词已挂版本：{keyword.name}")

    call(
        "PUT",
        f"/projects/{project_id}/content-versions/{version_id}/links",
        token,
        {
            "question_ids": [str(q) for q in question_ids],
            "citation_ids": [str(c) for c in citation_ids],
            "fact_ids": [],
        },
    )
    print(f"题目关联 {len(question_ids)} 条，证据关联 {len(citation_ids)} 条")

    if plan_id is None and channel_id is not None:
        scheduled = (datetime.now(LOCAL_TZ) + timedelta(days=1)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        created = call(
            "POST",
            f"/projects/{project_id}/plans",
            token,
            {
                "title": PLAN_TITLE,
                "plan_type": "article",
                "channel_id": str(channel_id),
                "content_item_id": item_id,
                "scheduled_at": scheduled.isoformat(),
                "status": "scheduled",
                "notes": "合成演练：仅验证排期与内容关联，不实际发布。",
            },
        )
        plan_id = created["data"]["id"]
        print(f"创建 mock 排期：{plan_id} @ {scheduled.isoformat()}")
    elif plan_id:
        print(f"复用 mock 排期：{plan_id}")

    links = call(
        "GET",
        f"/projects/{project_id}/content-versions/{version_id}/links",
        token,
    )["data"]
    print("内容关联结果：")
    print(f"  version_id={version_id}")
    print(f"  question_ids={links['question_ids']}")
    print(f"  citation_ids={links['citation_ids']}")
    print(f"  keyword_links={[(k.name, version_id) for k in keyword_rows]}")
    print(f"  plan_id={plan_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
