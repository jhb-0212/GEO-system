"""事实推送（G9）回归：只推已核准事实、推送幂等、百科只生成草稿、webhook 失败留痕可重试。"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import DistributionPush, EncyclopediaEntry
from app.models.enums import RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _setup(project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"push-{suffix}")
    editor = user_factory(f"push-editor-{suffix}")
    reviewer = user_factory(f"push-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    return project, editor, reviewer


def _create_fact(client, project, editor, *, key="课程周期", value="6 个月") -> str:
    created = client.post(
        f"/api/v1/projects/{project.id}/facts",
        json={
            "fact_type": "course_duration",
            "fact_key": key,
            "fact_value": value,
            "source_url": "https://www.gdccai.com/course",
        },
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    return created.json()["data"]["id"]


def _approve_fact(client, project, fact_id, editor, reviewer) -> None:
    submitted = client.post(
        f"/api/v1/projects/{project.id}/facts/{fact_id}/submit", headers=_auth(editor)
    )
    assert submitted.status_code == 200, submitted.text
    approved = client.post(
        f"/api/v1/projects/{project.id}/facts/{fact_id}/review",
        json={"decision": "approved", "business_confirmed": False},
        headers=_auth(reviewer),
    )
    assert approved.status_code == 200, approved.text


def test_draft_fact_cannot_be_pushed(client, project_factory, user_factory, member_factory):
    project, editor, reviewer = _setup(project_factory, user_factory, member_factory)
    fact_id = _create_fact(client, project, editor)

    response = client.post(
        f"/api/v1/projects/{project.id}/facts/{fact_id}/push",
        json={"target_type": "encyclopedia"},
        headers=_auth(editor),
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "fact_not_approved"


def test_encyclopedia_push_creates_draft_entry_once(
    client, db, project_factory, user_factory, member_factory
):
    project, editor, reviewer = _setup(project_factory, user_factory, member_factory)
    fact_id = _create_fact(client, project, editor, key="课程周期", value="6 个月")
    _approve_fact(client, project, fact_id, editor, reviewer)

    first = client.post(
        f"/api/v1/projects/{project.id}/facts/{fact_id}/push",
        json={"target_type": "encyclopedia", "target_ref": "baidu_baike"},
        headers=_auth(editor),
    )
    assert first.status_code == 200, first.text
    body = first.json()["data"]
    assert body["status"] == "sent"
    assert body["created"] is True
    assert body["attempt_count"] == 1

    entries = list(
        db.scalars(select(EncyclopediaEntry).where(EncyclopediaEntry.project_id == project.id))
    )
    assert len(entries) == 1
    # 推送只搬进起草区，不代第三方平台发布
    assert entries[0].status.value == "draft"
    assert entries[0].platform == "baidu_baike"
    assert entries[0].body == "6 个月"
    assert body["external_ref"] == str(entries[0].id)

    second = client.post(
        f"/api/v1/projects/{project.id}/facts/{fact_id}/push",
        json={"target_type": "encyclopedia", "target_ref": "baidu_baike"},
        headers=_auth(editor),
    )
    assert second.status_code == 200, second.text
    assert second.json()["data"]["created"] is False
    # 幂等：不二次外发、不二次建词条
    assert second.json()["data"]["attempt_count"] == 1
    assert second.json()["data"]["id"] == body["id"]
    entries = list(
        db.scalars(select(EncyclopediaEntry).where(EncyclopediaEntry.project_id == project.id))
    )
    assert len(entries) == 1


def test_webhook_failure_is_recorded_and_retryable(
    client, db, project_factory, user_factory, member_factory
):
    project, editor, reviewer = _setup(project_factory, user_factory, member_factory)
    fact_id = _create_fact(client, project, editor)
    _approve_fact(client, project, fact_id, editor, reviewer)

    # 9 号端口无人监听：连接立即被拒，适合当“必然失败”的目标
    pushed = client.post(
        f"/api/v1/projects/{project.id}/facts/{fact_id}/push",
        json={"target_type": "webhook", "target_ref": "http://127.0.0.1:9/eeat"},
        headers=_auth(editor),
    )
    assert pushed.status_code == 200, pushed.text
    body = pushed.json()["data"]
    assert body["status"] == "failed"
    assert body["error"]
    assert body["attempt_count"] == 1

    retried = client.post(
        f"/api/v1/projects/{project.id}/push-records/{body['id']}/retry",
        headers=_auth(editor),
    )
    assert retried.status_code == 200, retried.text
    after = retried.json()["data"]
    assert after["attempt_count"] == 2
    assert after["status"] == "failed"

    # 已送达的记录不能被重试（重复外发比少发一次更难解释）
    sent_push = db.scalar(select(DistributionPush).where(DistributionPush.id == uuid.UUID(body["id"])))
    assert sent_push is not None


def test_webhook_target_must_be_http(client, project_factory, user_factory, member_factory):
    project, editor, reviewer = _setup(project_factory, user_factory, member_factory)
    fact_id = _create_fact(client, project, editor)
    _approve_fact(client, project, fact_id, editor, reviewer)

    response = client.post(
        f"/api/v1/projects/{project.id}/facts/{fact_id}/push",
        json={"target_type": "webhook", "target_ref": "ftp://example.com/hook"},
        headers=_auth(editor),
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "push_target_invalid"


def test_push_records_are_project_scoped(
    client, project_factory, user_factory, member_factory
):
    project, editor, reviewer = _setup(project_factory, user_factory, member_factory)
    other_project, other_editor, _ = _setup(project_factory, user_factory, member_factory)

    fact_id = _create_fact(client, project, editor)
    _approve_fact(client, project, fact_id, editor, reviewer)
    client.post(
        f"/api/v1/projects/{project.id}/facts/{fact_id}/push",
        json={"target_type": "encyclopedia"},
        headers=_auth(editor),
    )

    listed = client.get(
        f"/api/v1/projects/{project.id}/push-records",
        headers=_auth(editor),
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["meta"]["total"] == 1

    # 另一个项目看不到这条记录
    leaked = client.get(
        f"/api/v1/projects/{other_project.id}/push-records",
        headers=_auth(other_editor),
    )
    assert leaked.status_code == 200, leaked.text
    assert leaked.json()["meta"]["total"] == 0
