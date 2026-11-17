"""审批职责分离：提交人不能审批自己提交的内容版本 / 报价。"""

import uuid

from sqlalchemy import select, update

from app.core.security import create_access_token
from app.models import AuditLog, ContentVersion
from app.models.enums import RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_content_version_submitter_cannot_review_own_submission(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"sep-content-{suffix}")
    editor = user_factory(f"sep-ed-{suffix}")
    reviewer = user_factory(f"sep-rv-{suffix}")
    admin = user_factory(f"sep-pa-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    base = f"/api/v1/projects/{project.id}"

    item = client.post(
        f"{base}/contents",
        json={"title": f"职责分离-{suffix}", "kind": "master"},
        headers=_auth(editor),
    )
    assert item.status_code == 201, item.text
    item_id = item.json()["data"]["item_id"]
    version = client.post(
        f"{base}/contents/{item_id}/versions",
        json={"body": "职责分离验证正文", "change_note": "初稿"},
        headers=_auth(editor),
    )
    assert version.status_code == 201, version.text
    version_id = uuid.UUID(version.json()["data"]["version_id"])
    submitted = client.post(
        f"{base}/content-versions/{version_id}/submit", headers=_auth(editor)
    )
    assert submitted.status_code == 200, submitted.text

    # 让 reviewer 成为该版本的提交人，模拟"同一人既提交又审批"
    row = db.scalar(select(ContentVersion).where(ContentVersion.id == version_id))
    assert row is not None
    row.submitted_by = reviewer.id
    row.created_by = reviewer.id
    db.commit()

    blocked = client.post(
        f"{base}/content-versions/{version_id}/review",
        json={"decision": "approved"},
        headers=_auth(reviewer),
    )
    assert blocked.status_code == 400, blocked.text
    assert blocked.json()["error"]["code"] == "review_self_not_allowed"

    # 换一个没有提交过的审批人即可通过，说明规则只拦"自己批自己"
    allowed = client.post(
        f"{base}/content-versions/{version_id}/review",
        json={"decision": "approved"},
        headers=_auth(admin),
    )
    assert allowed.status_code == 200, allowed.text


def test_quote_submitter_cannot_review_own_quote(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"sep-quote-{suffix}")
    editor = user_factory(f"sep-qed-{suffix}")
    reviewer = user_factory(f"sep-qrv-{suffix}")
    admin = user_factory(f"sep-qpa-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    base = f"/api/v1/projects/{project.id}"

    plan = client.post(
        f"{base}/plans",
        json={"title": f"职责分离报价-{suffix}", "plan_type": "article"},
        headers=_auth(editor),
    )
    assert plan.status_code == 201, plan.text
    plan_id = plan.json()["data"]["id"]
    quote = client.post(
        f"{base}/media-quotes",
        json={"plan_id": plan_id, "unit_price": 100, "quantity": 2, "currency": "CNY"},
        headers=_auth(editor),
    )
    assert quote.status_code == 201, quote.text
    quote_id = uuid.UUID(quote.json()["data"]["id"])

    # 把 quote.create 的操作者改成 reviewer，模拟"报价是 reviewer 自己提的"
    db.execute(
        update(AuditLog)
        .where(AuditLog.action == "quote.create", AuditLog.target_id == quote_id)
        .values(actor_id=reviewer.id)
    )
    db.commit()

    blocked = client.post(
        f"{base}/media-quotes/{quote_id}/review",
        json={"decision": "approved"},
        headers=_auth(reviewer),
    )
    assert blocked.status_code == 400, blocked.text
    assert blocked.json()["error"]["code"] == "review_self_not_allowed"

    allowed = client.post(
        f"{base}/media-quotes/{quote_id}/review",
        json={"decision": "approved"},
        headers=_auth(admin),
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["data"]["status"] == "approved"
