"""竞品台账 / 指标口径 / 成员候选 三类新接口的回归与权限边界。"""

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import Competitor, MetricDefinition, AuditLog, ProjectMember
from app.models.enums import MetricStatus, RoleCode


def _auth(user) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"
    }


# ---------- 竞品 ----------


def test_competitor_create_list_patch_and_duplicate(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"comp-{suffix}")
    editor = user_factory(f"comp-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    created = client.post(
        f"/api/v1/projects/{project.id}/competitors",
        json={"name": f"竞品-{suffix}", "domain": "rival.example.com", "notes": "头号竞品"},
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    competitor_id = created.json()["data"]["id"]

    listed = client.get(
        f"/api/v1/projects/{project.id}/competitors", headers=_auth(editor)
    )
    assert listed.status_code == 200, listed.text
    data = listed.json()["data"]
    assert any(row["id"] == competitor_id for row in data)
    row = next(item for item in data if item["id"] == competitor_id)
    assert row["name"] == f"竞品-{suffix}"
    assert row["domain"] == "rival.example.com"
    assert row["is_active"] is True

    patched = client.patch(
        f"/api/v1/projects/{project.id}/competitors/{competitor_id}",
        json={"is_active": False, "notes": "暂停跟踪"},
        headers=_auth(editor),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["is_active"] is False
    assert patched.json()["data"]["notes"] == "暂停跟踪"

    # 同名再建 → 400 competitor_conflict
    dup = client.post(
        f"/api/v1/projects/{project.id}/competitors",
        json={"name": f"竞品-{suffix}"},
        headers=_auth(editor),
    )
    assert dup.status_code == 400, dup.text
    assert dup.json()["error"]["code"] == "competitor_conflict"

    # 审计留痕
    audits = db.scalars(
        select(AuditLog).where(
            AuditLog.project_id == project.id, AuditLog.action == "competitor.create"
        )
    ).all()
    assert len(audits) == 1


def test_competitor_write_requires_competitor_write_capability(
    client, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"comp-ro-{suffix}")
    viewer = user_factory(f"comp-viewer-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)

    # 只读角色可查看，但不可新增
    listed = client.get(
        f"/api/v1/projects/{project.id}/competitors", headers=_auth(viewer)
    )
    assert listed.status_code == 200, listed.text
    denied = client.post(
        f"/api/v1/projects/{project.id}/competitors",
        json={"name": f"越权竞品-{suffix}"},
        headers=_auth(viewer),
    )
    assert denied.status_code == 403, denied.text


# ---------- 指标口径 ----------


def test_metric_create_rule_version_increment_and_retire(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"metric-{suffix}")
    editor = user_factory(f"metric-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    code = f"metric_{suffix}"

    first = client.post(
        f"/api/v1/projects/{project.id}/metric-definitions",
        json={"code": code, "name": "品牌提及率", "formula": "品牌提及有效回答 / 有效回答"},
        headers=_auth(editor),
    )
    assert first.status_code == 201, first.text
    assert first.json()["data"]["rule_version"] == 1

    second = client.post(
        f"/api/v1/projects/{project.id}/metric-definitions",
        json={"code": code, "name": "品牌提及率 v2", "formula": "命中数 / 有效数"},
        headers=_auth(editor),
    )
    assert second.status_code == 201, second.text
    assert second.json()["data"]["rule_version"] == 2

    listed = client.get(
        f"/api/v1/projects/{project.id}/metric-definitions", headers=_auth(editor)
    )
    assert listed.status_code == 200, listed.text
    versions = [row for row in listed.json()["data"] if row["code"] == code]
    assert {row["rule_version"] for row in versions} == {1, 2}

    # 停用 v1 → effective_to 自动落库
    metric_id = second.json()["data"]["id"]
    retired = client.patch(
        f"/api/v1/projects/{project.id}/metric-definitions/{metric_id}",
        json={"status": "retired"},
        headers=_auth(editor),
    )
    assert retired.status_code == 200, retired.text
    assert retired.json()["data"]["status"] == "retired"
    assert retired.json()["data"]["effective_to"] is not None

    metric_row = db.scalar(
        select(MetricDefinition).where(MetricDefinition.id == uuid.UUID(metric_id))
    )
    assert metric_row is not None and metric_row.status == MetricStatus.RETIRED


def test_metric_manage_capability_boundary(
    client, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"metric-ro-{suffix}")
    viewer = user_factory(f"metric-viewer-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)

    listed = client.get(
        f"/api/v1/projects/{project.id}/metric-definitions", headers=_auth(viewer)
    )
    assert listed.status_code == 200, listed.text
    denied = client.post(
        f"/api/v1/projects/{project.id}/metric-definitions",
        json={"code": f"x_{suffix}", "name": "x", "formula": "x / y"},
        headers=_auth(viewer),
    )
    assert denied.status_code == 403, denied.text


# ---------- 成员候选 ----------


def test_member_candidates_excludes_existing_and_requires_admin(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"mem-{suffix}")
    admin = user_factory(f"mem-admin-{suffix}")
    existing = user_factory(f"mem-existing-{suffix}")
    candidate = user_factory(f"mem-candidate-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    member_factory(project, existing, RoleCode.EDITOR)

    resp = client.get(
        f"/api/v1/projects/{project.id}/members/candidates?q=mem-",
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    ids = {row["id"] for row in resp.json()["data"]}
    assert str(candidate.id) in ids
    assert str(existing.id) not in ids  # 已是成员，不再作为候选
    row = next(item for item in resp.json()["data"] if item["id"] == str(candidate.id))
    assert row["username"] == f"mem-candidate-{suffix}"

    # 非项目管理员访问候选搜索 → 403
    denied = client.get(
        f"/api/v1/projects/{project.id}/members/candidates",
        headers=_auth(existing),
    )
    assert denied.status_code == 403, denied.text


def test_member_list_returns_user_identity(
    client, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"memlist-{suffix}")
    admin = user_factory(f"memlist-admin-{suffix}")
    editor = user_factory(f"memlist-editor-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    member_factory(project, editor, RoleCode.EDITOR)

    resp = client.get(
        f"/api/v1/projects/{project.id}/members", headers=_auth(admin)
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["data"]
    editor_row = next(r for r in rows if r["user_id"] == str(editor.id))
    assert editor_row["username"] == f"memlist-editor-{suffix}"
    assert editor_row["display_name"] == f"memlist-editor-{suffix}"
    assert editor_row["role_code"] == "editor"


def test_member_deactivate_is_soft_and_guarded(
    client, db, project_factory, user_factory, member_factory
):
    """停用成员只置 is_active=false，保留成员行；不能停用自己，非管理员无权操作。"""
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"memdel-{suffix}")
    admin = user_factory(f"memdel-admin-{suffix}")
    editor = user_factory(f"memdel-editor-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    editor_member = member_factory(project, editor, RoleCode.EDITOR)

    denied = client.delete(
        f"/api/v1/projects/{project.id}/members/{editor_member.id}",
        headers=_auth(editor),
    )
    assert denied.status_code == 403, denied.text

    stopped = client.delete(
        f"/api/v1/projects/{project.id}/members/{editor_member.id}",
        headers=_auth(admin),
    )
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["data"]["member_id"] == str(editor_member.id)
    assert stopped.json()["data"]["role_code"] == "editor"

    row = db.get(ProjectMember, editor_member.id)
    assert row is not None
    assert row.is_active is False

    listed = client.get(
        f"/api/v1/projects/{project.id}/members", headers=_auth(admin)
    )
    assert listed.status_code == 200, listed.text
    target = next(
        r for r in listed.json()["data"] if r["member_id"] == str(editor_member.id)
    )
    assert target["is_active"] is False

    self_member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == admin.id,
        )
    )
    assert self_member is not None
    self_stop = client.delete(
        f"/api/v1/projects/{project.id}/members/{self_member.id}",
        headers=_auth(admin),
    )
    assert self_stop.status_code == 400, self_stop.text
    assert self_stop.json()["error"]["code"] == "cannot_remove_self"


def test_deactivated_member_is_grantable_again(
    client, db, project_factory, user_factory, member_factory
):
    """停用成员应回到候选列表，并可通过授予接口原地复活（不新增成员行）。"""
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"memregrant-{suffix}")
    admin = user_factory(f"memregrant-admin-{suffix}")
    editor = user_factory(f"memregrant-editor-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    editor_member = member_factory(project, editor, RoleCode.EDITOR)

    before = client.get(
        f"/api/v1/projects/{project.id}/members/candidates?q=memregrant-",
        headers=_auth(admin),
    )
    assert before.status_code == 200, before.text
    assert str(editor.id) not in {row["id"] for row in before.json()["data"]}

    stopped = client.delete(
        f"/api/v1/projects/{project.id}/members/{editor_member.id}",
        headers=_auth(admin),
    )
    assert stopped.status_code == 200, stopped.text

    after = client.get(
        f"/api/v1/projects/{project.id}/members/candidates?q=memregrant-",
        headers=_auth(admin),
    )
    assert after.status_code == 200, after.text
    assert str(editor.id) in {row["id"] for row in after.json()["data"]}

    regrant = client.post(
        f"/api/v1/projects/{project.id}/members",
        json={"user_id": str(editor.id), "role_code": "viewer"},
        headers=_auth(admin),
    )
    assert regrant.status_code == 201, regrant.text
    assert regrant.json()["data"]["member_id"] == str(editor_member.id)
    row = db.get(ProjectMember, editor_member.id)
    assert row.is_active is True
    listed = client.get(
        f"/api/v1/projects/{project.id}/members", headers=_auth(admin)
    )
    target = next(
        r for r in listed.json()["data"] if r["member_id"] == str(editor_member.id)
    )
    assert target["is_active"] is True
    assert target["role_code"] == "viewer"
