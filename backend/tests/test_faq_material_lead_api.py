"""FAQ / 素材 / 线索字段与导出回归。"""

import uuid

from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token
from app.models import AuditLog
from app.models.enums import RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_faq_crud_and_public_read(client, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"faq-{suffix}")
    editor = user_factory(f"faq-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    created = client.post(
        f"/api/v1/projects/{project.id}/faqs",
        json={"question": "地址在哪里？", "answer": "广州天河。", "category": "到校", "status": "published", "sort_order": 1},
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    faq_id = created.json()["data"]["id"]

    listed = client.get(f"/api/v1/projects/{project.id}/faqs", headers=_auth(editor))
    assert listed.status_code == 200
    row = listed.json()["data"][0]
    assert row["question"] == "地址在哪里？"
    assert row["category"] == "到校"
    assert row["status"] == "published"
    assert row["created_at"] is not None

    filtered = client.get(
        f"/api/v1/projects/{project.id}/faqs",
        params={"category": "到校"},
        headers=_auth(editor),
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["data"]] == [faq_id]

    missing = client.get(
        f"/api/v1/projects/{project.id}/faqs",
        params={"category": "不存在"},
        headers=_auth(editor),
    )
    assert missing.status_code == 200
    assert missing.json()["data"] == []

    patched = client.patch(
        f"/api/v1/projects/{project.id}/faqs/{faq_id}",
        json={"status": "unpublished", "answer": "广州天河区。", "category": "  "},
        headers=_auth(editor),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["status"] == "unpublished"
    assert patched.json()["data"]["category"] is None

    deleted = client.delete(
        f"/api/v1/projects/{project.id}/faqs/{faq_id}",
        headers=_auth(editor),
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["data"]["status"] == "unpublished"
    assert deleted.json()["data"]["deleted_at"] is not None

    visible_after_delete = client.get(f"/api/v1/projects/{project.id}/faqs", headers=_auth(editor))
    assert visible_after_delete.status_code == 200
    assert visible_after_delete.json()["data"] == []

    deleted_page = client.get(
        f"/api/v1/projects/{project.id}/faqs",
        params={"deleted": "true"},
        headers=_auth(editor),
    )
    assert deleted_page.status_code == 200
    assert [item["id"] for item in deleted_page.json()["data"]] == [faq_id]

    restored = client.post(
        f"/api/v1/projects/{project.id}/faqs/{faq_id}/restore",
        headers=_auth(editor),
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["data"]["status"] == "draft"
    assert restored.json()["data"]["deleted_at"] is None

    visible_after_restore = client.get(f"/api/v1/projects/{project.id}/faqs", headers=_auth(editor))
    assert [item["id"] for item in visible_after_restore.json()["data"]] == [faq_id]

    public = client.get(f"/api/v1/public/projects/{project.code}/faqs")
    assert public.status_code == 200
    assert public.json()["data"] == []


def test_faq_soft_delete_published_records_audit(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"faq-del-{suffix}")
    editor = user_factory(f"faq-del-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    created = client.post(
        f"/api/v1/projects/{project.id}/faqs",
        json={"question": "上架后直接删除", "answer": "答案", "status": "published"},
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    faq_id = created.json()["data"]["id"]

    public_before = client.get(f"/api/v1/public/projects/{project.code}/faqs")
    assert [row["id"] for row in public_before.json()["data"]] == [faq_id]

    deleted = client.delete(f"/api/v1/projects/{project.id}/faqs/{faq_id}", headers=_auth(editor))
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["data"]["deleted_by"] == str(editor.id)

    public_after = client.get(f"/api/v1/public/projects/{project.code}/faqs")
    assert public_after.json()["data"] == []

    audit = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "faq.delete",
            AuditLog.target_id == uuid.UUID(faq_id),
        )
    )
    assert audit is not None
    assert audit.payload["was_published"] is True

    duplicate = client.delete(f"/api/v1/projects/{project.id}/faqs/{faq_id}", headers=_auth(editor))
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "faq_already_deleted"


def test_faq_pagination_isolation_permissions_and_categories(
    client, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"faq-page-{suffix}")
    other = project_factory(f"faq-other-{suffix}")
    editor = user_factory(f"faq-page-editor-{suffix}")
    viewer = user_factory(f"faq-page-viewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, viewer, RoleCode.VIEWER)

    ids = []
    for index, category in enumerate(["课程", "报名", "课程"]):
        response = client.post(
            f"/api/v1/projects/{project.id}/faqs",
            json={"question": f"分页问题 {index}", "answer": "答案", "category": category, "sort_order": index},
            headers=_auth(editor),
        )
        assert response.status_code == 201, response.text
        ids.append(response.json()["data"]["id"])

    first = client.get(
        f"/api/v1/projects/{project.id}/faqs",
        params={"page": 1, "page_size": 2},
        headers=_auth(editor),
    )
    assert first.status_code == 200
    assert first.json()["meta"]["total"] == 3
    assert [item["id"] for item in first.json()["data"]] == ids[:2]

    second = client.get(
        f"/api/v1/projects/{project.id}/faqs",
        params={"page": 2, "page_size": 2},
        headers=_auth(editor),
    )
    assert [item["id"] for item in second.json()["data"]] == ids[2:]

    by_category = client.get(
        f"/api/v1/projects/{project.id}/faqs",
        params={"category": "课程", "page_size": 2},
        headers=_auth(editor),
    )
    assert by_category.json()["meta"]["total"] == 2
    assert {item["id"] for item in by_category.json()["data"]} == {ids[0], ids[2]}

    categories = client.get(f"/api/v1/projects/{project.id}/faqs/categories", headers=_auth(editor))
    assert categories.status_code == 200
    assert set(categories.json()["data"]) == {"报名", "课程"}

    cross = client.get(f"/api/v1/projects/{other.id}/faqs", headers=_auth(editor))
    assert cross.status_code == 403
    assert cross.json()["error"]["code"] == "project_forbidden"

    viewer_read = client.get(f"/api/v1/projects/{project.id}/faqs", headers=_auth(viewer))
    assert viewer_read.status_code == 200
    viewer_write = client.post(
        f"/api/v1/projects/{project.id}/faqs",
        json={"question": "只读账号不能写", "answer": "答案"},
        headers=_auth(viewer),
    )
    assert viewer_write.status_code == 403


def test_material_upload_list_patch_and_download(
    client, db, tmp_path, monkeypatch, project_factory, user_factory, member_factory
):
    monkeypatch.setattr(settings, "evidence_local_root", str(tmp_path))
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"material-{suffix}")
    editor = user_factory(f"material-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    uploaded = client.post(
        f"/api/v1/projects/{project.id}/materials",
        data={"title": "招生简章", "category": "document", "description": "2026 版"},
        files={"file": ("brief.txt", b"hello material", "text/plain")},
        headers=_auth(editor),
    )
    assert uploaded.status_code == 201, uploaded.text
    material = uploaded.json()["data"]
    assert material["title"] == "招生简章"
    assert material["byte_size"] == len(b"hello material")
    assert len(material["checksum"]) == 64

    listed = client.get(f"/api/v1/projects/{project.id}/materials", headers=_auth(editor))
    assert listed.status_code == 200
    assert listed.json()["data"][0]["file_name"] == "brief.txt"

    patched = client.patch(
        f"/api/v1/projects/{project.id}/materials/{material['id']}",
        json={"title": "招生简章（修订）", "category": "case"},
        headers=_auth(editor),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["category"] == "case"

    downloaded = client.get(
        f"/api/v1/projects/{project.id}/materials/{material['id']}/download",
        headers=_auth(editor),
    )
    assert downloaded.status_code == 200
    assert downloaded.content == b"hello material"

    action = db.scalar(select(AuditLog).where(AuditLog.action == "material.upload"))
    assert action is not None


def test_project_list_has_owner_and_counts(client, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"project-{suffix}")
    admin = user_factory(f"project-admin-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)

    listed = client.get("/api/v1/projects", headers=_auth(admin))
    assert listed.status_code == 200, listed.text
    row = next(item for item in listed.json()["data"] if item["id"] == str(project.id))
    assert row["owner_name"] == admin.display_name
    assert row["updated_at"] is not None
    assert row["channel_count"] == 0
    assert row["task_count"] == 0


def test_lead_fields_patch_and_export(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"lead-{suffix}")
    lead_ops = user_factory(f"lead-ops-{suffix}")
    admin = user_factory(f"lead-admin-{suffix}")
    member_factory(project, lead_ops, RoleCode.LEAD_OPS)
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)

    created = client.post(
        f"/api/v1/projects/{project.id}/leads",
        json={"contact_name": "张三", "contact_phone": "13800000000", "lead_source": "官网"},
        headers=_auth(lead_ops),
    )
    assert created.status_code == 201, created.text
    lead_id = created.json()["data"]["id"]

    listed = client.get(f"/api/v1/projects/{project.id}/leads", headers=_auth(lead_ops))
    row = listed.json()["data"][0]
    assert row["created_at"] is not None
    assert row["updated_at"] is not None
    assert row["owner_name"] == lead_ops.display_name

    patched = client.patch(
        f"/api/v1/projects/{project.id}/leads/{lead_id}",
        json={"enrollment_status": "contacted", "note": "已电话沟通"},
        headers=_auth(lead_ops),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["enrollment_status"] == "contacted"
    assert patched.json()["data"]["note"] == "已电话沟通"

    forbidden = client.get(f"/api/v1/projects/{project.id}/leads/export", headers=_auth(lead_ops))
    assert forbidden.status_code == 403

    exported = client.get(f"/api/v1/projects/{project.id}/leads/export", headers=_auth(admin))
    assert exported.status_code == 200, exported.text
    assert "text/csv" in exported.headers["content-type"]
    assert "张三" in exported.text
    assert "contacted" in exported.text
    export_audit = db.scalar(select(AuditLog).where(AuditLog.action == "export"))
    assert export_audit is not None

def test_faq_category_normalization(client, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"faq-cat-{suffix}")
    editor = user_factory(f"faq-cat-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    for index, category in enumerate(["  课程  ", "课  程", "   "]):
        created = client.post(
            f"/api/v1/projects/{project.id}/faqs",
            json={"question": f"分类归一 {index}", "answer": "答案", "category": category},
            headers=_auth(editor),
        )
        assert created.status_code == 201, created.text

    rows = client.get(
        f"/api/v1/projects/{project.id}/faqs",
        params={"page_size": 100},
        headers=_auth(editor),
    )
    assert rows.status_code == 200
    assert {item["category"] for item in rows.json()["data"]} == {"课程", "课 程", None}

    categories = client.get(f"/api/v1/projects/{project.id}/faqs/categories", headers=_auth(editor))
    assert set(categories.json()["data"]) == {"课程", "课 程"}