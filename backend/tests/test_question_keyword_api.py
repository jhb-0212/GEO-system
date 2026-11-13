"""B2/B3 回归：题库版本、关键词软删、权限矩阵与跨项目隔离。"""

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import (
    AuditLog,
    ContentItem,
    ContentVersion,
    ContentVersionKeyword,
    Keyword,
    Question,
    QuestionVersion,
)
from app.models.enums import ContentKind, ContentStatus, RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_question_create_versions_and_status(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"q-{suffix}")
    editor = user_factory(f"q-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    created = client.post(
        f"/api/v1/projects/{project.id}/questions",
        json={
            "code": f"Q-{suffix}",
            "title": "零基础转行需要什么基础",
            "question_type": "general",
            "audience": "零基础转行者",
            "intent": "了解入门门槛",
            "text": "零基础转行需要什么基础？",
        },
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    question_id = created.json()["data"]["id"]
    assert created.json()["data"]["version_no"] == 1

    listed = client.get(
        f"/api/v1/projects/{project.id}/questions",
        params={"question_type": "general"},
        headers=_auth(editor),
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["meta"]["total"] == 1
    assert listed.json()["data"][0]["code"] == f"Q-{suffix}"
    assert listed.json()["data"][0]["current_version_no"] == 1

    versions = client.get(
        f"/api/v1/projects/{project.id}/questions/{question_id}/versions",
        headers=_auth(editor),
    )
    assert versions.status_code == 200, versions.text
    assert [row["version_no"] for row in versions.json()["data"]] == [1]
    assert versions.json()["data"][0]["text"] == "零基础转行需要什么基础？"

    appended = client.post(
        f"/api/v1/projects/{project.id}/questions/{question_id}/versions",
        json={"text": "零基础转行，先学哪些技能？", "change_note": "补充问法"},
        headers=_auth(editor),
    )
    assert appended.status_code == 201, appended.text
    assert appended.json()["data"]["version_no"] == 2

    patched = client.patch(
        f"/api/v1/projects/{project.id}/questions/{question_id}",
        json={"audience": "转行人群", "intent": "课程方向", "priority": 10, "status": "active"},
        headers=_auth(editor),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["status"] == "active"
    assert patched.json()["data"]["priority"] == 10

    invalid = client.patch(
        f"/api/v1/projects/{project.id}/questions/{question_id}",
        json={"status": "draft"},
        headers=_auth(editor),
    )
    assert invalid.status_code == 409, invalid.text
    assert invalid.json()["error"]["code"] == "question_status_conflict"

    archived = client.patch(
        f"/api/v1/projects/{project.id}/questions/{question_id}",
        json={"status": "archived"},
        headers=_auth(editor),
    )
    assert archived.status_code == 200, archived.text
    reactivated = client.patch(
        f"/api/v1/projects/{project.id}/questions/{question_id}",
        json={"status": "active"},
        headers=_auth(editor),
    )
    assert reactivated.status_code == 200, reactivated.text

    db_question = db.scalar(select(Question).where(Question.id == uuid.UUID(question_id)))
    assert db_question is not None
    assert db_question.current_version_no == 2
    rows = db.scalars(
        select(QuestionVersion)
        .where(QuestionVersion.question_id == db_question.id)
        .order_by(QuestionVersion.version_no)
    ).all()
    assert [row.text for row in rows] == [
        "零基础转行需要什么基础？",
        "零基础转行，先学哪些技能？",
    ]
    audits = db.scalars(
        select(AuditLog).where(
            AuditLog.project_id == project.id,
            AuditLog.target_id.in_([db_question.id, rows[1].id]),
        )
    ).all()
    assert {"question.create", "question.update", "question.version_add"} <= {
        row.action for row in audits
    }


def test_question_permissions_duplicate_and_isolation(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    p1 = project_factory(f"qp1-{suffix}")
    p2 = project_factory(f"qp2-{suffix}")
    editor = user_factory(f"qp-editor-{suffix}")
    viewer = user_factory(f"qp-viewer-{suffix}")
    reviewer = user_factory(f"qp-reviewer-{suffix}")
    member_factory(p1, editor, RoleCode.EDITOR)
    member_factory(p2, editor, RoleCode.EDITOR)
    member_factory(p1, viewer, RoleCode.VIEWER)
    member_factory(p1, reviewer, RoleCode.REVIEWER)

    body = {
        "code": f"QP-{suffix}",
        "title": "测试题目",
        "question_type": "brand",
        "text": "测试正文",
    }
    first = client.post(
        f"/api/v1/projects/{p1.id}/questions", json=body, headers=_auth(editor)
    )
    assert first.status_code == 201, first.text
    question_id = first.json()["data"]["id"]

    viewer_read = client.get(
        f"/api/v1/projects/{p1.id}/questions", headers=_auth(viewer)
    )
    assert viewer_read.status_code == 200
    viewer_write = client.post(
        f"/api/v1/projects/{p1.id}/questions", json=body, headers=_auth(viewer)
    )
    assert viewer_write.status_code == 403
    reviewer_write = client.post(
        f"/api/v1/projects/{p1.id}/questions", json=body, headers=_auth(reviewer)
    )
    assert reviewer_write.status_code == 403

    duplicate = client.post(
        f"/api/v1/projects/{p1.id}/questions", json=body, headers=_auth(editor)
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["error"]["code"] == "question_code_conflict"

    cross_project = client.get(
        f"/api/v1/projects/{p2.id}/questions/{question_id}/versions",
        headers=_auth(editor),
    )
    assert cross_project.status_code == 404, cross_project.text
    assert cross_project.json()["error"]["code"] == "question_missing"


def test_keyword_crud_soft_delete_and_content_version_link(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"kw-{suffix}")
    editor = user_factory(f"kw-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    created = client.post(
        f"/api/v1/projects/{project.id}/keywords",
        json={"name": f"目标词-{suffix}", "category": "brand", "priority": 5, "notes": "初始"},
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    keyword_id = created.json()["data"]["id"]
    assert created.json()["data"]["content_version_count"] == 0

    item = ContentItem(
        project_id=project.id,
        kind=ContentKind.MASTER,
        title="测试内容",
        status=ContentStatus.DRAFT,
        created_by=editor.id,
    )
    db.add(item)
    db.flush()
    version = ContentVersion(
        project_id=project.id,
        item_id=item.id,
        version_no=1,
        body="正文",
        content_hash="0" * 64,
        status=ContentStatus.DRAFT,
    )
    db.add(version)
    db.flush()
    db.add(
        ContentVersionKeyword(
            project_id=project.id,
            version_id=version.id,
            keyword_id=uuid.UUID(keyword_id),
        )
    )
    db.flush()

    listed = client.get(
        f"/api/v1/projects/{project.id}/keywords", headers=_auth(editor)
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["data"][0]["content_version_count"] == 1

    patched = client.patch(
        f"/api/v1/projects/{project.id}/keywords/{keyword_id}",
        json={"name": f"新目标词-{suffix}", "category": "competitor", "priority": 1},
        headers=_auth(editor),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["name"] == f"新目标词-{suffix}"
    assert patched.json()["data"]["category"] == "competitor"

    deleted = client.delete(
        f"/api/v1/projects/{project.id}/keywords/{keyword_id}", headers=_auth(editor)
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["data"]["is_active"] is False
    assert deleted.json()["data"]["content_version_count"] == 1

    db_keyword = db.scalar(select(Keyword).where(Keyword.id == uuid.UUID(keyword_id)))
    assert db_keyword is not None and db_keyword.is_active is False
    link = db.scalar(
        select(ContentVersionKeyword).where(
            ContentVersionKeyword.keyword_id == db_keyword.id
        )
    )
    assert link is not None
    audits = db.scalars(
        select(AuditLog).where(
            AuditLog.project_id == project.id,
            AuditLog.target_id == db_keyword.id,
        )
    ).all()
    assert {"keyword.create", "keyword.update", "keyword.delete"} <= {
        row.action for row in audits
    }


def test_keyword_permissions_duplicate_and_isolation(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    p1 = project_factory(f"kwp1-{suffix}")
    p2 = project_factory(f"kwp2-{suffix}")
    editor = user_factory(f"kwp-editor-{suffix}")
    viewer = user_factory(f"kwp-viewer-{suffix}")
    member_factory(p1, editor, RoleCode.EDITOR)
    member_factory(p2, editor, RoleCode.EDITOR)
    member_factory(p1, viewer, RoleCode.VIEWER)

    name = f"重复词-{suffix}"
    created = client.post(
        f"/api/v1/projects/{p1.id}/keywords",
        json={"name": name},
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    keyword_id = created.json()["data"]["id"]

    duplicate = client.post(
        f"/api/v1/projects/{p1.id}/keywords",
        json={"name": name},
        headers=_auth(editor),
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["error"]["code"] == "keyword_name_conflict"

    viewer_read = client.get(f"/api/v1/projects/{p1.id}/keywords", headers=_auth(viewer))
    assert viewer_read.status_code == 200
    viewer_write = client.post(
        f"/api/v1/projects/{p1.id}/keywords",
        json={"name": f"viewer-{suffix}"},
        headers=_auth(viewer),
    )
    assert viewer_write.status_code == 403

    cross_project = client.patch(
        f"/api/v1/projects/{p2.id}/keywords/{keyword_id}",
        json={"category": "other"},
        headers=_auth(editor),
    )
    assert cross_project.status_code == 404, cross_project.text
    assert cross_project.json()["error"]["code"] == "keyword_missing"
