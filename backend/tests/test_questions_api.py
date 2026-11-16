"""B2/B3: 题目正文版本不可覆盖，目标词关联必须限于本项目。"""

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import ContentItem, ContentVersion, QuestionVersion
from app.models.enums import ContentKind, ContentStatus, RoleCode


def _auth(user):
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_question_version_and_keyword_links(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"questions-{suffix}")
    editor = user_factory(f"editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    base = f"/api/v1/projects/{project.id}"
    headers = _auth(editor)

    created = client.post(f"{base}/questions", headers=headers, json={
        "code": "Q07", "title": "新题", "question_type": "general", "initial_text": "第一版问法",
    })
    assert created.status_code == 201, created.text
    question = created.json()["data"]
    assert question["status"] == "draft" and question["current_text"] == "第一版问法"
    question_id = question["id"]

    changed = client.patch(f"{base}/questions/{question_id}", headers=headers,
                           json={"audience": "学生", "intent": "择校", "priority": 20, "status": "active"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["data"]["current_text"] == "第一版问法"
    assert client.patch(f"{base}/questions/{question_id}", headers=headers,
                        json={"text": "越权覆盖"}).status_code == 422

    version = client.post(f"{base}/questions/{question_id}/versions", headers=headers,
                          json={"text": "第二版问法", "change_note": "调整措辞"})
    assert version.status_code == 201, version.text
    assert version.json()["data"]["version_no"] == 2
    versions = client.get(f"{base}/questions/{question_id}/versions", headers=headers)
    assert versions.status_code == 200
    assert [row["text"] for row in versions.json()["data"]] == ["第二版问法", "第一版问法"]
    assert db.scalar(select(QuestionVersion).where(QuestionVersion.question_id == uuid.UUID(question_id),
                                                  QuestionVersion.version_no == 1)).text == "第一版问法"

    content = ContentItem(project_id=project.id, kind=ContentKind.MASTER, title="测试内容",
                          status=ContentStatus.DRAFT, created_by=editor.id)
    db.add(content)
    db.flush()
    content_version = ContentVersion(project_id=project.id, item_id=content.id, version_no=1,
                                     body="内容", content_hash="0" * 64, status=ContentStatus.DRAFT,
                                     created_by=editor.id)
    db.add(content_version)
    db.flush()
    keyword = client.post(f"{base}/keywords", headers=headers, json={
        "name": "广州学校", "question_ids": [question_id], "content_version_ids": [str(content_version.id)],
    })
    assert keyword.status_code == 201, keyword.text
    assert keyword.json()["data"]["question_ids"] == [question_id]
    assert keyword.json()["data"]["content_version_ids"] == [str(content_version.id)]
    listed = client.get(f"{base}/keywords", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["meta"]["total"] == 1
    assert client.get(f"{base}/questions", headers=headers).json()["data"][0]["current_text"] == "第二版问法"


def test_question_keyword_project_scope_and_permissions(client, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    own = project_factory(f"own-{suffix}")
    other = project_factory(f"other-{suffix}")
    editor = user_factory(f"editor-scope-{suffix}")
    viewer = user_factory(f"viewer-scope-{suffix}")
    member_factory(own, editor, RoleCode.EDITOR)
    member_factory(other, editor, RoleCode.EDITOR)
    member_factory(own, viewer, RoleCode.VIEWER)
    own_base = f"/api/v1/projects/{own.id}"
    other_base = f"/api/v1/projects/{other.id}"
    question = client.post(f"{other_base}/questions", headers=_auth(editor), json={
        "code": "Q99", "title": "他项目题", "question_type": "brand", "initial_text": "他项目问法",
    }).json()["data"]
    assert client.get(f"{own_base}/questions/{question['id']}/versions", headers=_auth(editor)).status_code == 403
    cross = client.post(f"{own_base}/keywords", headers=_auth(editor), json={
        "name": "跨项目词", "question_ids": [question["id"]],
    })
    assert cross.status_code == 400 and cross.json()["error"]["code"] == "question_project_mismatch"
    assert client.post(f"{own_base}/questions", headers=_auth(viewer), json={
        "code": "Q01", "title": "只读", "question_type": "brand", "initial_text": "不可写",
    }).status_code == 403
    assert client.get(f"{own_base}/questions", headers=_auth(viewer)).status_code == 200
