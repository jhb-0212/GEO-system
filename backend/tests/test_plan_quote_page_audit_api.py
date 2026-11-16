"""计划、报价、公开站页面与系统审计的回归测试。"""

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import AuditLog, ContentPlan, MediaQuote, PublicPage
from app.models.enums import (
    ContentPlanStatus,
    PagePublishStatus,
    QuoteStatus,
    RoleCode,
)


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_plan_create_list_update_and_isolation(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    p1 = project_factory(f"pl1-{suffix}")
    p2 = project_factory(f"pl2-{suffix}")
    editor = user_factory(f"pl-editor-{suffix}")
    viewer = user_factory(f"pl-viewer-{suffix}")
    member_factory(p1, editor, RoleCode.EDITOR)
    member_factory(p2, editor, RoleCode.EDITOR)
    member_factory(p1, viewer, RoleCode.VIEWER)

    created = client.post(
        f"/api/v1/projects/{p1.id}/plans",
        json={
            "title": "双十一课程选题",
            "plan_type": "article",
            "scheduled_at": "2026-11-20T10:00:00+08:00",
            "notes": "首版排期",
        },
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    plan_id = created.json()["data"]["id"]

    listed = client.get(
        f"/api/v1/projects/{p1.id}/plans",
        params={"status": "proposed", "plan_type": "article"},
        headers=_auth(editor),
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["meta"]["total"] == 1
    assert listed.json()["data"][0]["title"] == "双十一课程选题"
    assert listed.json()["data"][0]["owner_id"] == str(editor.id)

    patched = client.patch(
        f"/api/v1/projects/{p1.id}/plans/{plan_id}",
        json={"status": "scheduled", "notes": "已排期"},
        headers=_auth(editor),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["status"] == "scheduled"
    assert patched.json()["data"]["notes"] == "已排期"

    viewer_write = client.post(
        f"/api/v1/projects/{p1.id}/plans",
        json={"title": "viewer", "plan_type": "video"},
        headers=_auth(viewer),
    )
    assert viewer_write.status_code == 403

    cross_project = client.patch(
        f"/api/v1/projects/{p2.id}/plans/{plan_id}",
        json={"notes": "越界"},
        headers=_auth(editor),
    )
    assert cross_project.status_code == 404, cross_project.text
    assert cross_project.json()["error"]["code"] == "plan_missing"

    db_plan = db.scalar(select(ContentPlan).where(ContentPlan.id == uuid.UUID(plan_id)))
    assert db_plan is not None and db_plan.status == ContentPlanStatus.SCHEDULED
    audits = db.scalars(
        select(AuditLog).where(
            AuditLog.project_id == p1.id,
            AuditLog.target_id == db_plan.id,
        )
    ).all()
    assert {"plan.create", "plan.update"} <= {row.action for row in audits}


def test_quote_create_budget_review_and_lock(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    p1 = project_factory(f"q1-{suffix}")
    p2 = project_factory(f"q2-{suffix}")
    editor = user_factory(f"q-editor-{suffix}")
    reviewer = user_factory(f"q-reviewer-{suffix}")
    member_factory(p1, editor, RoleCode.EDITOR)
    member_factory(p1, reviewer, RoleCode.REVIEWER)

    plan = client.post(
        f"/api/v1/projects/{p1.id}/plans",
        json={"title": "媒体合作选题", "plan_type": "article"},
        headers=_auth(editor),
    )
    assert plan.status_code == 201, plan.text
    plan_id = plan.json()["data"]["id"]

    created = client.post(
        f"/api/v1/projects/{p1.id}/media-quotes",
        json={"plan_id": plan_id, "unit_price": "100.50", "quantity": 2, "currency": "cny"},
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    quote_id = created.json()["data"]["id"]

    listed = client.get(
        f"/api/v1/projects/{p1.id}/media-quotes",
        params={"status": "pending"},
        headers=_auth(editor),
    )
    assert listed.status_code == 200, listed.text
    quote_row = listed.json()["data"][0]
    assert quote_row["budget"] == 201.0
    assert quote_row["currency"] == "CNY"

    editor_review = client.post(
        f"/api/v1/projects/{p1.id}/media-quotes/{quote_id}/review",
        json={"decision": "approved"},
        headers=_auth(editor),
    )
    assert editor_review.status_code == 403

    reviewed = client.post(
        f"/api/v1/projects/{p1.id}/media-quotes/{quote_id}/review",
        json={"decision": "approved", "note": "预算通过"},
        headers=_auth(reviewer),
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["data"]["status"] == "approved"
    assert reviewed.json()["data"]["approved_by"] == str(reviewer.id)
    assert reviewed.json()["data"]["approved_at"] is not None

    locked = client.patch(
        f"/api/v1/projects/{p1.id}/media-quotes/{quote_id}",
        json={"quantity": 3},
        headers=_auth(editor),
    )
    assert locked.status_code == 409, locked.text
    assert locked.json()["error"]["code"] == "quote_status_conflict"

    reviewer_create = client.post(
        f"/api/v1/projects/{p1.id}/media-quotes",
        json={"plan_id": plan_id, "unit_price": "10.00"},
        headers=_auth(reviewer),
    )
    assert reviewer_create.status_code == 403

    # 跨项目：有 content.review 的 reviewer 也只看得到 404，不暴露资源存在性
    p2_reviewer = user_factory(f"q2-reviewer-{suffix}")
    member_factory(p2, p2_reviewer, RoleCode.REVIEWER)
    cross_project = client.post(
        f"/api/v1/projects/{p2.id}/media-quotes/{quote_id}/review",
        json={"decision": "rejected"},
        headers=_auth(p2_reviewer),
    )
    assert cross_project.status_code == 404, cross_project.text
    assert cross_project.json()["error"]["code"] == "quote_missing"

    db_quote = db.scalar(select(MediaQuote).where(MediaQuote.id == uuid.UUID(quote_id)))
    assert db_quote is not None and db_quote.status == QuoteStatus.APPROVED
    audits = db.scalars(
        select(AuditLog).where(
            AuditLog.project_id == p1.id,
            AuditLog.target_id == db_quote.id,
        )
    ).all()
    assert {"quote.create", "quote.review"} <= {row.action for row in audits}


def test_page_registration_and_publish_status(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    p1 = project_factory(f"pg1-{suffix}")
    p2 = project_factory(f"pg2-{suffix}")
    editor = user_factory(f"pg-editor-{suffix}")
    viewer = user_factory(f"pg-viewer-{suffix}")
    member_factory(p1, editor, RoleCode.EDITOR)
    member_factory(p2, editor, RoleCode.EDITOR)
    member_factory(p1, viewer, RoleCode.VIEWER)

    slug = f"faq-{suffix}"
    created = client.post(
        f"/api/v1/projects/{p1.id}/pages",
        json={
            "slug": slug,
            "title": "常见问题",
            "page_type": "faq",
            "url": f"https://example.com/{slug}",
            "canonical_url": f"https://example.com/{slug}/",
        },
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    page_id = created.json()["data"]["id"]

    duplicate = client.post(
        f"/api/v1/projects/{p1.id}/pages",
        json={
            "slug": slug,
            "title": "重复页面",
            "page_type": "other",
            "url": "https://example.com/dup",
        },
        headers=_auth(editor),
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["error"]["code"] == "page_slug_conflict"

    listed = client.get(
        f"/api/v1/projects/{p1.id}/pages",
        params={"publish_status": "draft", "page_type": "faq"},
        headers=_auth(editor),
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["meta"]["total"] == 1
    assert listed.json()["data"][0]["last_published_at"] is None

    published = client.patch(
        f"/api/v1/projects/{p1.id}/pages/{page_id}",
        json={"publish_status": "published"},
        headers=_auth(editor),
    )
    assert published.status_code == 200, published.text
    assert published.json()["data"]["publish_status"] == "published"
    assert published.json()["data"]["last_published_at"] is not None

    viewer_write = client.post(
        f"/api/v1/projects/{p1.id}/pages",
        json={"slug": f"viewer-{suffix}", "title": "viewer", "page_type": "other", "url": "https://example.com/v"},
        headers=_auth(viewer),
    )
    assert viewer_write.status_code == 403

    cross_project = client.patch(
        f"/api/v1/projects/{p2.id}/pages/{page_id}",
        json={"title": "越界"},
        headers=_auth(editor),
    )
    assert cross_project.status_code == 404, cross_project.text
    assert cross_project.json()["error"]["code"] == "page_missing"

    db_page = db.scalar(select(PublicPage).where(PublicPage.id == uuid.UUID(page_id)))
    assert db_page is not None and db_page.publish_status == PagePublishStatus.PUBLISHED
    audits = db.scalars(
        select(AuditLog).where(
            AuditLog.project_id == p1.id,
            AuditLog.target_id == db_page.id,
        )
    ).all()
    assert {"page.create", "page.update"} <= {row.action for row in audits}


def test_system_audit_only_system_admin_and_only_null_project(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"au-{suffix}")
    sys_admin = user_factory(f"au-sys-{suffix}", is_system_admin=True)
    project_admin = user_factory(f"au-pa-{suffix}")
    editor = user_factory(f"au-editor-{suffix}")
    member_factory(project, project_admin, RoleCode.PROJECT_ADMIN)
    member_factory(project, editor, RoleCode.EDITOR)

    system_row = AuditLog(
        project_id=None,
        actor_id=sys_admin.id,
        action="project.create",
        target_type="project",
        target_id=project.id,
        payload={"code": project.code},
    )
    project_row = AuditLog(
        project_id=project.id,
        actor_id=editor.id,
        action="export",
        target_type="stats",
        target_id=None,
        payload={"row_count": 1},
    )
    db.add_all([system_row, project_row])
    db.flush()

    system_result = client.get(
        "/api/v1/system/audit-logs",
        params={"action": "project.create"},
        headers=_auth(sys_admin),
    )
    assert system_result.status_code == 200, system_result.text
    assert system_result.json()["meta"]["total"] == 1
    assert system_result.json()["data"][0]["action"] == "project.create"

    project_admin_denied = client.get(
        "/api/v1/system/audit-logs",
        headers=_auth(project_admin),
    )
    assert project_admin_denied.status_code == 403
    assert project_admin_denied.json()["error"]["code"] == "system_admin_only"

    editor_denied = client.get(
        "/api/v1/system/audit-logs",
        headers=_auth(editor),
    )
    assert editor_denied.status_code == 403

    project_result = client.get(
        f"/api/v1/projects/{project.id}/audit-logs",
        headers=_auth(project_admin),
    )
    assert project_result.status_code == 200, project_result.text
    assert project_result.json()["meta"]["total"] == 1
    assert project_result.json()["data"][0]["action"] == "export"
