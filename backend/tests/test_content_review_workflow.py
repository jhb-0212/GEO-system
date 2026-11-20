"""Submission, queue, decision and history form one review path."""

import uuid

from app.core.security import create_access_token
from app.models.enums import RoleCode


def _auth(user):
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_content_review_queue_and_history(client, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"review-{suffix}")
    editor = user_factory(f"review-editor-{suffix}")
    reviewer = user_factory(f"review-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    base = f"/api/v1/projects/{project.id}"

    item = client.post(
        f"{base}/contents", json={"title": "审核测试母稿", "kind": "master"}, headers=_auth(editor)
    )
    assert item.status_code == 201
    item_id = item.json()["data"]["item_id"]
    version = client.post(
        f"{base}/contents/{item_id}/versions",
        json={"body": "真实正文内容", "change_note": "初稿"},
        headers=_auth(editor),
    )
    assert version.status_code == 201
    version_id = version.json()["data"]["version_id"]

    review_url = f"{base}/content-versions/{version_id}/review"
    assert client.post(review_url, json={"decision": "approved"}, headers=_auth(reviewer)).status_code == 409
    submitted = client.post(f"{base}/content-versions/{version_id}/submit", headers=_auth(editor))
    assert submitted.status_code == 200
    assert submitted.json()["data"]["status"] == "pending_review"
    assert client.post(f"{base}/content-versions/{version_id}/submit", headers=_auth(editor)).status_code == 409
    assert client.patch(
        f"{base}/content-versions/{version_id}/body",
        json={"body": "提交后偷改正文"},
        headers=_auth(editor),
    ).status_code == 409

    queue = client.get(f"{base}/content-versions", headers=_auth(reviewer))
    assert queue.status_code == 200
    assert any(row["version_id"] == version_id and row["title"] == "审核测试母稿" for row in queue.json()["data"])
    row = next(row for row in queue.json()["data"] if row["version_id"] == version_id)
    assert row["status_label"] == "待审"
    detail = client.get(f"{base}/content-versions/{version_id}", headers=_auth(reviewer))
    assert detail.status_code == 200
    assert detail.json()["data"]["body"] == "真实正文内容"
    assert detail.json()["data"]["content_hash"]

    approved = client.post(
        review_url, json={"decision": "approved", "comment": "通过"}, headers=_auth(reviewer)
    )
    assert approved.status_code == 200
    assert client.post(review_url, json={"decision": "approved"}, headers=_auth(reviewer)).status_code == 409
    assert client.patch(
        f"{base}/content-versions/{version_id}/body",
        json={"body": "审核后偷改正文"},
        headers=_auth(editor),
    ).status_code == 409
    next_version = client.post(
        f"{base}/contents/{item_id}/versions",
        json={"body": "审核通过后的修订正文", "change_note": "补充说明"},
        headers=_auth(editor),
    )
    assert next_version.status_code == 201
    assert next_version.json()["data"]["version_no"] == 2
    history = client.get(f"{base}/content-versions/{version_id}/reviews", headers=_auth(editor))
    assert history.status_code == 200
    assert history.json()["data"][0]["decision"] == "approved"
    assert history.json()["data"][0]["content_hash_snapshot"]


def test_rejected_version_can_resubmit(client, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"rej-{suffix}")
    editor = user_factory(f"rej-editor-{suffix}")
    reviewer = user_factory(f"rej-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    base = f"/api/v1/projects/{project.id}"

    item = client.post(
        f"{base}/contents", json={"title": "驳回重测母稿", "kind": "master"}, headers=_auth(editor)
    )
    item_id = item.json()["data"]["item_id"]
    version = client.post(
        f"{base}/contents/{item_id}/versions",
        json={"body": "待驳回正文", "change_note": "初稿"},
        headers=_auth(editor),
    )
    version_id = version.json()["data"]["version_id"]
    assert client.post(f"{base}/content-versions/{version_id}/submit", headers=_auth(editor)).status_code == 200
    rejected = client.post(
        f"{base}/content-versions/{version_id}/review",
        json={"decision": "rejected", "comment": "需要修改"},
        headers=_auth(reviewer),
    )
    assert rejected.status_code == 200

    resubmitted = client.post(
        f"{base}/content-versions/{version_id}/submit", headers=_auth(editor)
    )
    assert resubmitted.status_code == 200
    assert resubmitted.json()["data"]["status"] == "pending_review"
