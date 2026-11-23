"""FAQ / 素材 / 线索字段与导出回归。"""

import uuid

from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token
from app.models import AuditLog
from app.models.enums import RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _submit_review(client, project_id, faq_id: str, user):
    return client.post(
        f"/api/v1/projects/{project_id}/faqs/{faq_id}/submit-review",
        headers=_auth(user),
    )


def _review_faq(client, project_id, faq_id: str, user, action: str, comment: str | None = None):
    return client.post(
        f"/api/v1/projects/{project_id}/faqs/{faq_id}/review",
        json={"action": action, "comment": comment},
        headers=_auth(user),
    )


def test_faq_crud_and_public_read(client, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"faq-{suffix}")
    editor = user_factory(f"faq-editor-{suffix}")
    reviewer = user_factory(f"faq-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)

    created = client.post(
        f"/api/v1/projects/{project.id}/faqs",
        json={"question": "地址在哪里？", "answer": "广州天河。", "category": "到校", "status": "draft", "sort_order": 1},
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    faq_id = created.json()["data"]["id"]

    submitted = _submit_review(client, project.id, faq_id, editor)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["data"]["status"] == "pending_review"

    published = _review_faq(client, project.id, faq_id, reviewer, "approve", "内容无误")
    assert published.status_code == 200, published.text
    assert published.json()["data"]["status"] == "published"
    assert published.json()["data"]["review_comment"] == "内容无误"
    assert published.json()["data"]["reviewed_by"] == str(reviewer.id)
    assert published.json()["data"]["reviewed_at"] is not None

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

    searched_answer = client.get(
        f"/api/v1/projects/{project.id}/faqs",
        params={"q": "天河"},
        headers=_auth(editor),
    )
    assert searched_answer.status_code == 200
    assert [item["id"] for item in searched_answer.json()["data"]] == [faq_id]
    assert searched_answer.json()["meta"]["total"] == 1

    searched_title = client.get(
        f"/api/v1/projects/{project.id}/faqs",
        params={"q": "地址"},
        headers=_auth(editor),
    )
    assert [item["id"] for item in searched_title.json()["data"]] == [faq_id]

    searched_none = client.get(
        f"/api/v1/projects/{project.id}/faqs",
        params={"q": "  "},
        headers=_auth(editor),
    )
    assert searched_none.status_code == 200
    assert [item["id"] for item in searched_none.json()["data"]] == [faq_id]

    # LIKE 通配符按字面处理：搜「%」不能把全部数据带出来，搜「_」也不能匹配任意单字符
    for wildcard in ("%", "_"):
        searched_wildcard = client.get(
            f"/api/v1/projects/{project.id}/faqs",
            params={"q": wildcard},
            headers=_auth(editor),
        )
        assert searched_wildcard.status_code == 200
        assert searched_wildcard.json()["data"] == [], wildcard

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
    reviewer = user_factory(f"faq-del-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)

    created = client.post(
        f"/api/v1/projects/{project.id}/faqs",
        json={"question": "上架后直接删除", "answer": "答案", "status": "draft"},
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    faq_id = created.json()["data"]["id"]
    submitted = _submit_review(client, project.id, faq_id, editor)
    assert submitted.status_code == 200, submitted.text
    published = _review_faq(client, project.id, faq_id, reviewer, "approve")
    assert published.status_code == 200, published.text

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
        files={"file": ("brief.txt", b"hello material", "text/html")},
        headers=_auth(editor),
    )
    assert uploaded.status_code == 201, uploaded.text
    material = uploaded.json()["data"]
    assert material["title"] == "招生简章"
    assert material["byte_size"] == len(b"hello material")
    assert len(material["checksum"]) == 64
    # 客户端声明的 text/html 被忽略，按扩展名重算
    assert material["content_type"] == "text/plain"

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


def test_lead_fields_patch_and_export(client, db, project_factory, user_factory, member_factory, monkeypatch):
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
    export_audit = db.scalar(
        select(AuditLog)
        .where(
            AuditLog.action == "export",
            AuditLog.target_type == "leads",
            AuditLog.project_id == project.id,
        )
        .order_by(AuditLog.created_at.desc())
    )
    assert export_audit is not None
    assert export_audit.payload["row_count"] == 1

    second = client.post(
        f"/api/v1/projects/{project.id}/leads",
        json={"contact_name": "李四", "contact_phone": "13900000000", "lead_source": "到校"},
        headers=_auth(lead_ops),
    )
    assert second.status_code == 201, second.text
    monkeypatch.setattr(settings, "export_sync_row_limit", 1)
    blocked = client.get(f"/api/v1/projects/{project.id}/leads/export", headers=_auth(admin))
    assert blocked.status_code == 400, blocked.text
    assert blocked.json()["error"]["code"] == "export_too_large"

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


def test_faq_publish_requires_independent_review(
    client, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"faq-review-{suffix}")
    editor = user_factory(f"faq-review-editor-{suffix}")
    reviewer = user_factory(f"faq-review-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)

    created = client.post(
        f"/api/v1/projects/{project.id}/faqs",
        json={"question": "审核门禁问题", "answer": "草稿答案", "status": "draft"},
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    faq_id = created.json()["data"]["id"]

    # 编辑不能直接发布，审核角色也不能把 PATCH 当审核入口。
    editor_publish = client.patch(
        f"/api/v1/projects/{project.id}/faqs/{faq_id}",
        json={"status": "published"},
        headers=_auth(editor),
    )
    assert editor_publish.status_code == 403, editor_publish.text
    assert editor_publish.json()["error"]["code"] == "faq_publish_requires_review"

    reviewer_patch = client.patch(
        f"/api/v1/projects/{project.id}/faqs/{faq_id}",
        json={"status": "published"},
        headers=_auth(reviewer),
    )
    assert reviewer_patch.status_code == 403, reviewer_patch.text
    assert reviewer_patch.json()["error"]["code"] == "faq_review_endpoint_required"

    editor_review = _review_faq(client, project.id, faq_id, editor, "approve")
    assert editor_review.status_code == 403, editor_review.text

    submitted = _submit_review(client, project.id, faq_id, editor)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["data"]["status"] == "pending_review"
    assert submitted.json()["data"]["review_comment"] is None

    # 待审正文锁定：编辑不能一边送审一边改内容，必须先撤回。
    pending_edit = client.patch(
        f"/api/v1/projects/{project.id}/faqs/{faq_id}",
        json={"answer": "送审后偷改答案"},
        headers=_auth(editor),
    )
    assert pending_edit.status_code == 409, pending_edit.text
    assert pending_edit.json()["error"]["code"] == "faq_pending_review_locked"

    withdrawn = client.patch(
        f"/api/v1/projects/{project.id}/faqs/{faq_id}",
        json={"status": "draft"},
        headers=_auth(editor),
    )
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["data"]["status"] == "draft"

    edited = client.patch(
        f"/api/v1/projects/{project.id}/faqs/{faq_id}",
        json={"answer": "撤回后修改的答案"},
        headers=_auth(editor),
    )
    assert edited.status_code == 200, edited.text

    resubmitted = _submit_review(client, project.id, faq_id, editor)
    assert resubmitted.status_code == 200, resubmitted.text

    approved = _review_faq(client, project.id, faq_id, reviewer, "approve", "内容无误")
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["status"] == "published"
    assert approved.json()["data"]["review_comment"] == "内容无误"
    assert approved.json()["data"]["reviewed_by"] == str(reviewer.id)
    assert approved.json()["data"]["reviewed_at"] is not None

    public = client.get(f"/api/v1/public/projects/{project.code}/faqs")
    assert [row["id"] for row in public.json()["data"]] == [faq_id]

    locked = client.patch(
        f"/api/v1/projects/{project.id}/faqs/{faq_id}",
        json={"answer": "绕过审核直接改答案"},
        headers=_auth(editor),
    )
    assert locked.status_code == 409, locked.text
    assert locked.json()["error"]["code"] == "faq_published_content_locked"

    unpublish_and_edit = client.patch(
        f"/api/v1/projects/{project.id}/faqs/{faq_id}",
        json={"status": "unpublished", "answer": "下架后修改的答案"},
        headers=_auth(editor),
    )
    assert unpublish_and_edit.status_code == 200, unpublish_and_edit.text
    assert unpublish_and_edit.json()["data"]["status"] == "unpublished"

    reviewer_edit = client.patch(
        f"/api/v1/projects/{project.id}/faqs/{faq_id}",
        json={"answer": "审核角色试图改正文"},
        headers=_auth(reviewer),
    )
    assert reviewer_edit.status_code == 403, reviewer_edit.text
    assert reviewer_edit.json()["error"]["code"] == "faq_content_write_forbidden"

    resubmitted_after_unpublish = _submit_review(client, project.id, faq_id, editor)
    assert resubmitted_after_unpublish.status_code == 200, resubmitted_after_unpublish.text
    reapproved = _review_faq(client, project.id, faq_id, reviewer, "approve")
    assert reapproved.status_code == 200, reapproved.text
    assert reapproved.json()["data"]["status"] == "published"

    direct_publish_create = client.post(
        f"/api/v1/projects/{project.id}/faqs",
        json={"question": "新建即发布", "answer": "答案", "status": "published"},
        headers=_auth(editor),
    )
    assert direct_publish_create.status_code == 403, direct_publish_create.text
    assert direct_publish_create.json()["error"]["code"] == "faq_publish_requires_review"

    direct_pending_create = client.post(
        f"/api/v1/projects/{project.id}/faqs",
        json={"question": "新建即送审", "answer": "答案", "status": "pending_review"},
        headers=_auth(editor),
    )
    assert direct_pending_create.status_code == 403, direct_pending_create.text
    assert direct_pending_create.json()["error"]["code"] == "faq_create_requires_draft"


def test_faq_review_queue_and_reject_flow(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"faq-queue-{suffix}")
    editor = user_factory(f"faq-queue-editor-{suffix}")
    reviewer = user_factory(f"faq-queue-reviewer-{suffix}")
    viewer = user_factory(f"faq-queue-viewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    member_factory(project, viewer, RoleCode.VIEWER)

    created_ids = []
    for index in range(2):
        created = client.post(
            f"/api/v1/projects/{project.id}/faqs",
            json={"question": f"待审问题 {index}", "answer": "答案", "status": "draft"},
            headers=_auth(editor),
        )
        assert created.status_code == 201, created.text
        created_ids.append(created.json()["data"]["id"])

    empty_queue = client.get(
        f"/api/v1/projects/{project.id}/faqs/review-queue",
        headers=_auth(reviewer),
    )
    assert empty_queue.status_code == 200, empty_queue.text
    assert empty_queue.json()["data"] == []
    assert empty_queue.json()["meta"]["total"] == 0

    editor_queue = client.get(
        f"/api/v1/projects/{project.id}/faqs/review-queue",
        headers=_auth(editor),
    )
    assert editor_queue.status_code == 403, editor_queue.text
    viewer_queue = client.get(
        f"/api/v1/projects/{project.id}/faqs/review-queue",
        headers=_auth(viewer),
    )
    assert viewer_queue.status_code == 403, viewer_queue.text

    target_id = created_ids[0]
    submitted = _submit_review(client, project.id, target_id, editor)
    assert submitted.status_code == 200, submitted.text

    queue = client.get(
        f"/api/v1/projects/{project.id}/faqs/review-queue",
        headers=_auth(reviewer),
    )
    assert queue.status_code == 200, queue.text
    assert queue.json()["meta"]["total"] == 1
    queued = queue.json()["data"][0]
    assert queued["id"] == target_id
    assert queued["status"] == "pending_review"
    assert queued["review_comment"] is None

    reject_without_comment = _review_faq(
        client, project.id, target_id, reviewer, "reject"
    )
    assert reject_without_comment.status_code == 400, reject_without_comment.text
    assert reject_without_comment.json()["error"]["code"] == "faq_review_comment_required"

    rejected = _review_faq(
        client, project.id, target_id, reviewer, "reject", "答案口径不完整，请补充"
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["data"]["status"] == "rejected"
    assert rejected.json()["data"]["review_comment"] == "答案口径不完整，请补充"
    assert rejected.json()["data"]["reviewed_by"] == str(reviewer.id)
    assert rejected.json()["data"]["reviewed_at"] is not None

    queue_after_reject = client.get(
        f"/api/v1/projects/{project.id}/faqs/review-queue",
        headers=_auth(reviewer),
    )
    assert queue_after_reject.json()["data"] == []

    public = client.get(f"/api/v1/public/projects/{project.code}/faqs")
    assert public.json()["data"] == []

    listed = client.get(f"/api/v1/projects/{project.id}/faqs", headers=_auth(editor))
    row = next(item for item in listed.json()["data"] if item["id"] == target_id)
    assert row["status"] == "rejected"
    assert row["review_comment"] == "答案口径不完整，请补充"

    edited = client.patch(
        f"/api/v1/projects/{project.id}/faqs/{target_id}",
        json={"answer": "补充完整后的答案"},
        headers=_auth(editor),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["data"]["review_comment"] == "答案口径不完整，请补充"

    resubmitted = _submit_review(client, project.id, target_id, editor)
    assert resubmitted.status_code == 200, resubmitted.text
    assert resubmitted.json()["data"]["status"] == "pending_review"
    assert resubmitted.json()["data"]["review_comment"] is None
    assert resubmitted.json()["data"]["reviewed_by"] is None

    queue_after_resubmit = client.get(
        f"/api/v1/projects/{project.id}/faqs/review-queue",
        headers=_auth(reviewer),
    )
    assert [item["id"] for item in queue_after_resubmit.json()["data"]] == [target_id]

    approved = _review_faq(
        client, project.id, target_id, reviewer, "approve", "补充后通过"
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["status"] == "published"

    public_after_approve = client.get(f"/api/v1/public/projects/{project.code}/faqs")
    assert [row["id"] for row in public_after_approve.json()["data"]] == [target_id]

    submit_audits = db.scalars(
        select(AuditLog).where(
            AuditLog.action == "faq.submit_review",
            AuditLog.target_id == uuid.UUID(target_id),
        )
    ).all()
    assert len(submit_audits) == 2
    review_audits = db.scalars(
        select(AuditLog).where(
            AuditLog.action == "faq.review",
            AuditLog.target_id == uuid.UUID(target_id),
        )
    ).all()
    assert len(review_audits) == 2
    reject_audit = next(
        item for item in review_audits if item.payload["review_action"] == "reject"
    )
    assert reject_audit.payload["review_comment"] == "答案口径不完整，请补充"


def test_faq_public_scope_blocks_sensitive_publish(
    client, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"faq-scope-{suffix}")
    editor = user_factory(f"faq-scope-editor-{suffix}")
    reviewer = user_factory(f"faq-scope-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)

    for question in (
        "两个班型的学费分别是多少？",
        "最近一期什么时候开班？",
        "退款边界怎么定义？",
    ):
        draft = client.post(
            f"/api/v1/projects/{project.id}/faqs",
            json={"question": question, "answer": "内部口径，不对外。", "status": "draft"},
            headers=_auth(editor),
        )
        assert draft.status_code == 201, draft.text
        faq_id = draft.json()["data"]["id"]

        submitted = _submit_review(client, project.id, faq_id, editor)
        assert submitted.status_code == 200, submitted.text
        publish = _review_faq(client, project.id, faq_id, reviewer, "approve")
        assert publish.status_code == 400, publish.text
        assert publish.json()["error"]["code"] == "faq_public_scope_forbidden"
        still_pending = client.get(
            f"/api/v1/projects/{project.id}/faqs",
            headers=_auth(editor),
        )
        assert next(item for item in still_pending.json()["data"] if item["id"] == faq_id)["status"] == "pending_review"

    public = client.get(f"/api/v1/public/projects/{project.code}/faqs")
    assert public.status_code == 200
    assert public.json()["data"] == []
