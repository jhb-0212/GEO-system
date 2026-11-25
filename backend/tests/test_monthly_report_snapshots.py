"""P05 月度报告快照：冻结、不可变、权限与审计回归。"""

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import AuditLog
from app.models.enums import RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _lead(client, project, actor, name: str) -> str:
    response = client.post(
        f"/api/v1/projects/{project.id}/leads",
        json={
            "contact_name": name,
            "contact_phone": "13800000000",
            "lead_source": "官网",
            "is_valid": True,
        },
        headers=_auth(actor),
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def test_monthly_snapshot_freezes_report_and_stays_immutable(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"monthly-snapshot-{suffix}")
    admin = user_factory(f"monthly-admin-{suffix}")
    editor = user_factory(f"monthly-editor-{suffix}")
    lead_ops = user_factory(f"monthly-leads-{suffix}")
    viewer = user_factory(f"monthly-viewer-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, lead_ops, RoleCode.LEAD_OPS)
    member_factory(project, viewer, RoleCode.VIEWER)

    _lead(client, project, lead_ops, "首月线索")
    month = "2026-11"

    frozen = client.post(
        f"/api/v1/projects/{project.id}/stats/monthly/snapshots",
        params={"month": month},
        headers=_auth(admin),
    )
    assert frozen.status_code == 201, frozen.text
    snapshot = frozen.json()["data"]
    assert snapshot["month"] == month
    assert snapshot["captured_by_name"] == admin.display_name
    assert snapshot["report"]["leads"]["total"] == 1
    assert snapshot["report"]["month"] == month
    assert snapshot["definitions"]["leads_included"] is True
    assert len(snapshot["snapshot_hash"]) == 64
    assert snapshot["report"]["entry_breakdown"] == []

    duplicate = client.post(
        f"/api/v1/projects/{project.id}/stats/monthly/snapshots",
        params={"month": month},
        headers=_auth(editor),
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["error"]["code"] == "monthly_report_snapshot_exists"

    audit = db.scalar(
        select(AuditLog).where(
            AuditLog.project_id == project.id,
            AuditLog.action == "stats.monthly_snapshot",
            AuditLog.target_id == uuid.UUID(snapshot["snapshot_id"]),
        )
    )
    assert audit is not None
    assert audit.payload["month"] == month
    assert audit.payload["snapshot_hash"] == snapshot["snapshot_hash"]

    # 冻结后再进一条线索：实时月报会变，历史快照不能变。
    _lead(client, project, lead_ops, "冻结后线索")
    live = client.get(
        f"/api/v1/projects/{project.id}/stats/monthly",
        params={"month": month},
        headers=_auth(admin),
    )
    assert live.status_code == 200, live.text
    assert live.json()["data"]["leads"]["total"] == 2

    detail = client.get(
        f"/api/v1/projects/{project.id}/stats/monthly/snapshots/{snapshot['snapshot_id']}",
        headers=_auth(viewer),
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["report"]["leads"]["total"] == 1

    history = client.get(
        f"/api/v1/projects/{project.id}/stats/monthly/snapshots",
        headers=_auth(viewer),
    )
    assert history.status_code == 200, history.text
    rows = history.json()["data"]
    assert len(rows) == 1
    assert rows[0]["snapshot_id"] == snapshot["snapshot_id"]
    assert rows[0]["captured_by_name"] == admin.display_name


def test_monthly_snapshot_permission_and_lead_scope(
    client, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"monthly-scope-{suffix}")
    reviewer = user_factory(f"monthly-reviewer-{suffix}")
    editor = user_factory(f"monthly-editor2-{suffix}")
    viewer = user_factory(f"monthly-viewer2-{suffix}")
    member_factory(project, reviewer, RoleCode.REVIEWER)
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, viewer, RoleCode.VIEWER)

    denied = client.post(
        f"/api/v1/projects/{project.id}/stats/monthly/snapshots",
        params={"month": "2026-10"},
        headers=_auth(viewer),
    )
    assert denied.status_code == 403, denied.text

    # 审核有 content.review、没有 lead.read：允许冻结，但线索段必须裁剪为空。
    reviewer_freeze = client.post(
        f"/api/v1/projects/{project.id}/stats/monthly/snapshots",
        params={"month": "2026-10"},
        headers=_auth(reviewer),
    )
    assert reviewer_freeze.status_code == 201, reviewer_freeze.text
    assert reviewer_freeze.json()["data"]["report"]["leads"] is None
    assert reviewer_freeze.json()["data"]["definitions"]["leads_included"] is False

    # 编辑有 monitoring.execute：同样可冻结。
    editor_freeze = client.post(
        f"/api/v1/projects/{project.id}/stats/monthly/snapshots",
        params={"month": "2026-09"},
        headers=_auth(editor),
    )
    assert editor_freeze.status_code == 201, editor_freeze.text
    assert editor_freeze.json()["data"]["report"]["leads"] is None

    bad_month = client.post(
        f"/api/v1/projects/{project.id}/stats/monthly/snapshots",
        params={"month": "2026-13"},
        headers=_auth(editor),
    )
    assert bad_month.status_code == 400, bad_month.text
    assert bad_month.json()["error"]["code"] == "invalid_month"
