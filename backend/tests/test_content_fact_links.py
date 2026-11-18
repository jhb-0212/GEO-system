"""内容版本关联权威事实、审批拦截与过期/修订提示回归。"""

from __future__ import annotations

import uuid

from app.core.security import create_access_token
from app.models.enums import RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _create_fact(client, project, editor, *, key="课程周期", value="6 个月") -> dict:
    created = client.post(
        f"/api/v1/projects/{project.id}/facts",
        json={
            "fact_type": "course_duration",
            "fact_key": key,
            "fact_value": value,
            "source_document": "2026 招生简章.pdf",
        },
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    return created.json()["data"]


def _approve_fact(client, project, editor, reviewer, fact_id: str) -> dict:
    submitted = client.post(
        f"/api/v1/projects/{project.id}/facts/{fact_id}/submit", headers=_auth(editor)
    )
    assert submitted.status_code == 200, submitted.text
    approved = client.post(
        f"/api/v1/projects/{project.id}/facts/{fact_id}/review",
        json={"decision": "approved"},
        headers=_auth(reviewer),
    )
    assert approved.status_code == 200, approved.text
    return approved.json()["data"]


def _create_content_version(client, project, editor, *, body="课程周期为 6 个月。") -> str:
    item = client.post(
        f"/api/v1/projects/{project.id}/contents",
        json={"title": "事实联动测试稿", "kind": "master"},
        headers=_auth(editor),
    )
    assert item.status_code == 201, item.text
    item_id = item.json()["data"]["item_id"]
    version = client.post(
        f"/api/v1/projects/{project.id}/contents/{item_id}/versions",
        json={"body": body, "change_note": "初稿"},
        headers=_auth(editor),
    )
    assert version.status_code == 201, version.text
    return version.json()["data"]["version_id"]


def _link_facts(client, project, editor, version_id: str, fact_ids: list[str], *, confirm=False):
    return client.put(
        f"/api/v1/projects/{project.id}/content-versions/{version_id}/links",
        json={"fact_ids": fact_ids, "confirm_fact_revisions": confirm},
        headers=_auth(editor),
    )


def _submit(client, project, editor, version_id: str) -> None:
    response = client.post(
        f"/api/v1/projects/{project.id}/content-versions/{version_id}/submit",
        headers=_auth(editor),
    )
    assert response.status_code == 200, response.text


def _review(client, project, reviewer, version_id: str, decision="approved"):
    return client.post(
        f"/api/v1/projects/{project.id}/content-versions/{version_id}/review",
        json={"decision": decision},
        headers=_auth(reviewer),
    )


def test_content_approval_blocks_unapproved_fact_and_links_show_warning(
    client, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"cf-draft-{suffix}")
    editor = user_factory(f"cf-editor-{suffix}")
    reviewer = user_factory(f"cf-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)

    fact = _create_fact(client, project, editor)
    version_id = _create_content_version(client, project, editor)
    linked = _link_facts(client, project, editor, version_id, [fact["id"]])
    assert linked.status_code == 200, linked.text
    link_data = linked.json()["data"]
    assert link_data["fact_ids"] == [fact["id"]]
    assert link_data["fact_links"][0]["warning"] == "事实未批准"
    assert link_data["fact_links"][0]["stale"] is True

    _submit(client, project, editor, version_id)
    blocked = _review(client, project, reviewer, version_id)
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["code"] == "content_fact_unverified"
    assert "事实未批准" in blocked.json()["error"]["message"]

    _approve_fact(client, project, editor, reviewer, fact["id"])
    approved = _review(client, project, reviewer, version_id)
    assert approved.status_code == 200, approved.text


def test_content_approval_blocks_expired_fact(client, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"cf-expired-{suffix}")
    editor = user_factory(f"cf-exp-editor-{suffix}")
    reviewer = user_factory(f"cf-exp-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)

    fact = _create_fact(client, project, editor)
    _approve_fact(client, project, editor, reviewer, fact["id"])
    version_id = _create_content_version(client, project, editor)
    assert _link_facts(client, project, editor, version_id, [fact["id"]]).status_code == 200
    _submit(client, project, editor, version_id)

    expired = client.post(
        f"/api/v1/projects/{project.id}/facts/{fact['id']}/expire",
        json={"reason": "招生简章已更新"},
        headers=_auth(reviewer),
    )
    assert expired.status_code == 200, expired.text

    links = client.get(
        f"/api/v1/projects/{project.id}/content-versions/{version_id}/links",
        headers=_auth(reviewer),
    )
    assert links.status_code == 200
    assert "事实已过期" in links.json()["data"]["fact_links"][0]["warning"]

    blocked = _review(client, project, reviewer, version_id)
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["code"] == "content_fact_unverified"
    assert "事实已过期" in blocked.json()["error"]["message"]


def test_revised_fact_requires_explicit_reconfirmation(
    client, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"cf-revised-{suffix}")
    editor = user_factory(f"cf-rev-editor-{suffix}")
    reviewer = user_factory(f"cf-rev-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)

    fact = _create_fact(client, project, editor)
    _approve_fact(client, project, editor, reviewer, fact["id"])
    version_id = _create_content_version(client, project, editor)
    assert _link_facts(client, project, editor, version_id, [fact["id"]]).status_code == 200
    _submit(client, project, editor, version_id)

    revised = client.patch(
        f"/api/v1/projects/{project.id}/facts/{fact['id']}",
        json={"fact_value": "8 个月"},
        headers=_auth(editor),
    )
    assert revised.status_code == 200, revised.text
    _approve_fact(client, project, editor, reviewer, fact["id"])

    blocked = _review(client, project, reviewer, version_id)
    assert blocked.status_code == 409, blocked.text
    assert "事实已修订" in blocked.json()["error"]["message"]

    reconfirmed = _link_facts(
        client, project, editor, version_id, [fact["id"]], confirm=True
    )
    assert reconfirmed.status_code == 200, reconfirmed.text
    assert reconfirmed.json()["data"]["fact_links"][0]["warning"] is None
    approved = _review(client, project, reviewer, version_id)
    assert approved.status_code == 200, approved.text


def test_link_rejects_fact_from_another_project(client, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project_a = project_factory(f"cf-a-{suffix}")
    project_b = project_factory(f"cf-b-{suffix}")
    editor_a = user_factory(f"cf-a-editor-{suffix}")
    editor_b = user_factory(f"cf-b-editor-{suffix}")
    member_factory(project_a, editor_a, RoleCode.EDITOR)
    member_factory(project_b, editor_b, RoleCode.EDITOR)

    fact_b = _create_fact(client, project_b, editor_b)
    version_id = _create_content_version(client, project_a, editor_a)
    rejected = _link_facts(client, project_a, editor_a, version_id, [fact_b["id"]])
    assert rejected.status_code == 404, rejected.text
    assert rejected.json()["error"]["code"] == "resource_missing"
