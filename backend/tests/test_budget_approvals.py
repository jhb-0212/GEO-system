"""四类预算审批：提交与审批分离，按项目范围隔离。"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.core.security import create_access_token
from app.models.enums import RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_budget_approval_role_matrix_and_transitions(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"budget-{suffix}")
    admin = user_factory(f"budget-admin-{suffix}")
    editor = user_factory(f"budget-editor-{suffix}")
    reviewer = user_factory(f"budget-reviewer-{suffix}")
    viewer = user_factory(f"budget-viewer-{suffix}")
    lead_ops = user_factory(f"budget-lead-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    member_factory(project, viewer, RoleCode.VIEWER)
    member_factory(project, lead_ops, RoleCode.LEAD_OPS)

    base = f"/api/v1/projects/{project.id}/budget-approvals"

    # 只读、招生没有预算读权限；编辑可读可提交；审核可读可审批。
    assert client.get(base, headers=_auth(viewer)).status_code == 403
    assert client.get(base, headers=_auth(lead_ops)).status_code == 403
    assert client.get(base, headers=_auth(editor)).status_code == 200

    created = client.post(
        base,
        json={
            "category": "development_hours",
            "title": "首月开发工时",
            "quantity": "40",
            "unit": "人时",
            "unit_price": "120",
            "amount": "4800",
            "currency": "CNY",
            "note": "含联调",
        },
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    assert row["status"] == "pending"
    assert row["requested_by"] == str(editor.id)
    budget_id = row["id"]

    # 编辑没有审批能力，不能自批。
    assert (
        client.post(
            f"{base}/{budget_id}/review",
            json={"decision": "approved"},
            headers=_auth(editor),
        ).status_code
        == 403
    )

    # 项目管理员有提交和审批能力，但职责分离要求不能审批自己提交的单据。
    admin_created = client.post(
        base,
        json={"category": "content_production", "title": "管理员自提", "amount": "500"},
        headers=_auth(admin),
    )
    assert admin_created.status_code == 201, admin_created.text
    self_review = client.post(
        f"{base}/{admin_created.json()['data']['id']}/review",
        json={"decision": "approved"},
        headers=_auth(admin),
    )
    assert self_review.status_code == 400, self_review.text
    assert self_review.json()["error"]["code"] == "review_self_not_allowed"

    approved = client.post(
        f"{base}/{budget_id}/review",
        json={"decision": "approved", "note": "预算内"},
        headers=_auth(reviewer),
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["status"] == "approved"
    assert approved.json()["data"]["approved_by"] == str(reviewer.id)

    again = client.post(
        f"{base}/{budget_id}/review",
        json={"decision": "rejected", "note": "重复审批"},
        headers=_auth(reviewer),
    )
    assert again.status_code == 400, again.text

    # 驳回必须写原因。
    rejected = client.post(
        base,
        json={
            "category": "monitoring_service",
            "title": "监测服务",
            "amount": "1000",
        },
        headers=_auth(editor),
    )
    assert rejected.status_code == 201, rejected.text
    missing_note = client.post(
        f"{base}/{rejected.json()['data']['id']}/review",
        json={"decision": "rejected"},
        headers=_auth(reviewer),
    )
    assert missing_note.status_code == 400, missing_note.text

    # 金额与数量×单价不一致时拒绝写入。
    mismatch = client.post(
        base,
        json={
            "category": "media_placement",
            "title": "渠道投放",
            "quantity": "2",
            "unit_price": "500",
            "amount": "900",
        },
        headers=_auth(editor),
    )
    assert mismatch.status_code == 422, mismatch.text


def test_budget_submit_requires_other_approver(
    client, db, project_factory, user_factory, member_factory
):
    """只有提交人自己能批时，拒绝提交，避免单据永久 pending。"""
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"budget-solo-{suffix}")
    editor = user_factory(f"budget-solo-editor-{suffix}")
    admin = user_factory(f"budget-solo-admin-{suffix}")
    reviewer = user_factory(f"budget-solo-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    base = f"/api/v1/projects/{project.id}/budget-approvals"

    denied = client.post(
        base,
        json={"category": "content_production", "title": "无审批人", "amount": "100"},
        headers=_auth(editor),
    )
    assert denied.status_code == 400, denied.text
    assert denied.json()["error"]["code"] == "budget_approver_required"

    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    editor_created = client.post(
        base,
        json={"category": "content_production", "title": "编辑提交", "amount": "100"},
        headers=_auth(editor),
    )
    assert editor_created.status_code == 201, editor_created.text

    # 项目管理员提交时，编辑没有审批能力，仍然没有“其他审批人”。
    admin_denied = client.post(
        base,
        json={"category": "content_production", "title": "管理员自提", "amount": "100"},
        headers=_auth(admin),
    )
    assert admin_denied.status_code == 400, admin_denied.text
    assert admin_denied.json()["error"]["code"] == "budget_approver_required"

    member_factory(project, reviewer, RoleCode.REVIEWER)
    admin_created = client.post(
        base,
        json={"category": "content_production", "title": "有审核人后提交", "amount": "100"},
        headers=_auth(admin),
    )
    assert admin_created.status_code == 201, admin_created.text


def test_budget_inactive_approver_is_not_counted(
    client, db, project_factory, user_factory, member_factory
):
    """项目成员仍 active，但账号已停用时，不能算作可审批人。"""
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"budget-inactive-{suffix}")
    editor = user_factory(f"budget-inactive-editor-{suffix}")
    reviewer = user_factory(f"budget-inactive-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    reviewer.is_active = False
    db.flush()
    base = f"/api/v1/projects/{project.id}/budget-approvals"

    denied = client.post(
        base,
        json={"category": "content_production", "title": "停用审批人", "amount": "100"},
        headers=_auth(editor),
    )
    assert denied.status_code == 400, denied.text
    assert denied.json()["error"]["code"] == "budget_approver_required"

    reviewer.is_active = True
    db.flush()
    created = client.post(
        base,
        json={"category": "content_production", "title": "恢复审批人", "amount": "100"},
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text


def test_budget_is_scoped_to_project(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project_a = project_factory(f"budget-a-{suffix}")
    project_b = project_factory(f"budget-b-{suffix}")
    editor_a = user_factory(f"budget-a-editor-{suffix}")
    admin_a = user_factory(f"budget-a-admin-{suffix}")
    member_factory(project_a, editor_a, RoleCode.EDITOR)
    member_factory(project_a, admin_a, RoleCode.PROJECT_ADMIN)

    created = client.post(
        f"/api/v1/projects/{project_a.id}/budget-approvals",
        json={"category": "content_production", "title": "内容制作", "amount": "600"},
        headers=_auth(editor_a),
    )
    assert created.status_code == 201, created.text
    budget_id = created.json()["data"]["id"]

    # 用别的项目路径审批同一单据必须查不到，不能跨项目写。
    cross = client.post(
        f"/api/v1/projects/{project_b.id}/budget-approvals/{budget_id}/review",
        json={"decision": "approved"},
        headers=_auth(admin_a),
    )
    assert cross.status_code == 403, cross.text


def test_budget_list_filters(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"budget-list-{suffix}")
    editor = user_factory(f"budget-list-editor-{suffix}")
    reviewer = user_factory(f"budget-list-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    base = f"/api/v1/projects/{project.id}/budget-approvals"
    for category, title in [
        ("development_hours", "开发"),
        ("content_production", "内容"),
        ("media_placement", "投放"),
        ("monitoring_service", "监测"),
    ]:
        response = client.post(
            base,
            json={"category": category, "title": title, "amount": "100"},
            headers=_auth(editor),
        )
        assert response.status_code == 201, response.text

    filtered = client.get(f"{base}?category=media_placement", headers=_auth(editor))
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["meta"]["total"] == 1
    assert filtered.json()["data"][0]["title"] == "投放"
    assert Decimal("100") == Decimal(str(filtered.json()["data"][0]["amount"]))
