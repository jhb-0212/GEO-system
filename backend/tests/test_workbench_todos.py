"""待办聚合接口：项目隔离、全量计数与今天/本周的右开边界。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.core.security import create_access_token
from app.models import ContentVersion
from app.models.enums import RoleCode


def _auth(user):
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _pending_review(client, base: str, headers, title: str) -> str:
    item = client.post(
        f"{base}/contents",
        json={"title": title, "kind": "master", "content_type": "faq"},
        headers=headers,
    )
    assert item.status_code == 201
    item_id = item.json()["data"]["item_id"]
    version = client.post(
        f"{base}/contents/{item_id}/versions",
        json={"body": "待办聚合测试正文", "change_note": "初稿"},
        headers=headers,
    )
    assert version.status_code == 201
    version_id = version.json()["data"]["version_id"]
    assert client.post(f"{base}/content-versions/{version_id}/submit", headers=headers).status_code == 200
    return version_id


def _review_group(payload: dict) -> dict:
    return next(group for group in payload["groups"] if group["label"] == "内容审核")


def test_todo_snapshot_counts_only_current_project(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project_a = project_factory(f"todo-a-{suffix}")
    project_b = project_factory(f"todo-b-{suffix}")
    editor = user_factory(f"todo-editor-{suffix}")
    member_factory(project_a, editor, RoleCode.EDITOR)
    member_factory(project_b, editor, RoleCode.EDITOR)
    headers = _auth(editor)

    _pending_review(client, f"/api/v1/projects/{project_a.id}", headers, "项目 A 待审稿")
    _pending_review(client, f"/api/v1/projects/{project_b.id}", headers, "项目 B 待审稿")

    response = client.get(
        f"/api/v1/projects/{project_a.id}/workbench/todos?range=all&tz_offset_minutes=480",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["project_id"] == str(project_a.id)
    group = _review_group(payload)
    assert group["counts"]["all"] == 1
    assert group["total"] == 1
    assert len(group["items"]) == 1
    assert group["items"][0]["title"] == "项目 A 待审稿"
    assert group["items"][0]["badge"] == "待审核"


def test_today_and_week_exclude_future_entries(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"todo-range-{suffix}")
    editor = user_factory(f"todo-range-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    headers = _auth(editor)
    base = f"/api/v1/projects/{project.id}"

    version_id = _pending_review(client, base, headers, "未来时间不应计入今天")
    version = db.get(ContentVersion, uuid.UUID(version_id))
    assert version is not None

    now = datetime.now(timezone.utc)
    next_week = now + timedelta(days=7 - now.weekday(), hours=1)
    version.submitted_at = next_week
    db.flush()

    for query, expected in (("today", 0), ("week", 0), ("all", 1)):
        response = client.get(
            f"{base}/workbench/todos?range={query}&tz_offset_minutes=480",
            headers=headers,
        )
        assert response.status_code == 200
        assert _review_group(response.json()["data"])["total"] == expected

    # 回到当前时间后，今天必须能看见这一项，避免把正常记录误排除。
    version.submitted_at = now - timedelta(minutes=5)
    db.flush()
    response = client.get(f"{base}/workbench/todos?range=today&tz_offset_minutes=480", headers=headers)
    assert _review_group(response.json()["data"])["total"] == 1
    assert "window" in response.json()["data"]
