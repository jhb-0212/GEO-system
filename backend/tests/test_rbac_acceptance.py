"""RBAC 验收用例（对应审核意见第四节的 9 条）。

全部走真实 HTTP 接口，不直接调用内部函数，确保“能不能调通”有可复现证据。
"""

import hashlib
import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import (
    AuditLog,
    Channel,
    ContentItem,
    ContentVersion,
    EvidenceFile,
    OutboxEvent,
    Project,
    ProjectMember,
    PublishAccount,
    PublishTask,
    Role,
)
from app.models.enums import (
    ChannelCategory,
    ChannelStatus,
    ContentKind,
    ContentStatus,
    EvidenceFileType,
    OutboxStatus,
    PublishTaskStatus,
    RoleCode,
)


def auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def make_team(project, user_factory, member_factory) -> dict[str, object]:
    suffix = uuid.uuid4().hex[:6]
    users = {}
    for role in (
        RoleCode.PROJECT_ADMIN,
        RoleCode.EDITOR,
        RoleCode.REVIEWER,
        RoleCode.VIEWER,
        RoleCode.LEAD_OPS,
    ):
        user = user_factory(f"{role.value}-{suffix}")
        member_factory(project, user, role)
        users[role] = user
    users["sys_admin"] = user_factory(f"sys-{suffix}", is_system_admin=True)
    return users


def make_content(db, project) -> ContentVersion:
    item = ContentItem(
        project_id=project.id,
        kind=ContentKind.MASTER,
        title="验收用母稿",
        status=ContentStatus.DRAFT,
    )
    db.add(item)
    db.flush()
    version = ContentVersion(
        project_id=project.id,
        item_id=item.id,
        version_no=1,
        body="原始正文",
        content_hash=_hash("原始正文"),
        status=ContentStatus.DRAFT,
    )
    db.add(version)
    db.flush()
    item.current_version_id = version.id
    return version


def make_publish_task(db, project) -> PublishTask:
    channel = Channel(
        project_id=project.id,
        code=f"ch-{uuid.uuid4().hex[:6]}",
        name="验收渠道",
        category=ChannelCategory.CONTENT_PLATFORM,
        status=ChannelStatus.CANDIDATE,
    )
    db.add(channel)
    db.flush()
    version = make_content(db, project)
    account = PublishAccount(
        project_id=project.id,
        channel_id=channel.id,
        account_name="验收账号",
        credential_ref="vault://test/account",
        is_active=True,
    )
    db.add(account)
    db.flush()
    task = PublishTask(
        project_id=project.id,
        version_id=version.id,
        channel_id=channel.id,
        account_id=account.id,
        task_key=f"tk-{uuid.uuid4().hex[:6]}",
        idempotency_key=f"idem-{uuid.uuid4().hex[:10]}",
        status=PublishTaskStatus.PENDING,
    )
    db.add(task)
    db.flush()
    return task


def test_01_project_admin_cannot_create_project(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"acc1-{uuid.uuid4().hex[:6]}")
    team = make_team(project, user_factory, member_factory)

    resp = client.post(
        "/api/v1/projects",
        json={"code": f"new-{uuid.uuid4().hex[:6]}", "name": "越级建项目"},
        headers=auth(team[RoleCode.PROJECT_ADMIN]),
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "system_admin_only"

    denial = db.scalars(
        select(AuditLog).where(
            AuditLog.actor_id == team[RoleCode.PROJECT_ADMIN].id,
            AuditLog.action == "permission_denied",
        )
    ).all()
    assert any((row.payload or {}).get("permission") == "project.create" for row in denial)


def test_02_project_admin_cannot_grant_admin_roles(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"acc2-{uuid.uuid4().hex[:6]}")
    team = make_team(project, user_factory, member_factory)
    newcomer = user_factory(f"new-{uuid.uuid4().hex[:6]}")

    for bad_role in ("project_admin", "sys_admin"):
        resp = client.post(
            f"/api/v1/projects/{project.id}/members",
            json={"user_id": str(newcomer.id), "role_code": bad_role},
            headers=auth(team[RoleCode.PROJECT_ADMIN]),
        )
        assert resp.status_code == 403, bad_role
        assert resp.json()["error"]["code"] == "insufficient_permission"

    ok = client.post(
        f"/api/v1/projects/{project.id}/members",
        json={"user_id": str(newcomer.id), "role_code": "editor"},
        headers=auth(team[RoleCode.PROJECT_ADMIN]),
    )
    assert ok.status_code == 201

    audit = db.scalars(
        select(AuditLog).where(AuditLog.action == "permission_change", AuditLog.project_id == project.id)
    ).all()
    assert len(audit) >= 1


def test_03_sys_admin_system_actions_only(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"acc3-{uuid.uuid4().hex[:6]}")
    team = make_team(project, user_factory, member_factory)
    sys_admin = team["sys_admin"]

    created = client.post(
        "/api/v1/projects",
        json={"code": f"sys-{uuid.uuid4().hex[:6]}", "name": "系统管理员建的项目"},
        headers=auth(sys_admin),
    )
    assert created.status_code == 201

    engine = client.post(
        "/api/v1/engines",
        json={"code": f"eng-{uuid.uuid4().hex[:6]}", "name": "验收引擎", "vendor": "验收厂商"},
        headers=auth(sys_admin),
    )
    assert engine.status_code == 201

    # 未加入项目 → 项目业务数据一律 403
    denied = client.get(f"/api/v1/projects/{project.id}/leads", headers=auth(sys_admin))
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "project_forbidden"

    denied2 = client.get(f"/api/v1/projects/{project.id}/monitoring/tasks", headers=auth(sys_admin))
    assert denied2.status_code == 403


def test_04_lead_ops_boundary(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"acc4-{uuid.uuid4().hex[:6]}")
    team = make_team(project, user_factory, member_factory)
    lead_user = team[RoleCode.LEAD_OPS]

    evidence = EvidenceFile(
        project_id=project.id,
        storage_key="not-exist.png",
        file_type=EvidenceFileType.SCREENSHOT,
    )
    db.add(evidence)
    db.flush()

    for path in (
        f"/api/v1/projects/{project.id}/monitoring/tasks",
        f"/api/v1/projects/{project.id}/channels",
        f"/api/v1/projects/{project.id}/publish/tasks",
        f"/api/v1/projects/{project.id}/evidence/{evidence.id}/download",
    ):
        resp = client.get(path, headers=auth(lead_user))
        assert resp.status_code == 403, path
        assert resp.json()["error"]["code"] == "insufficient_permission"

    created = client.post(
        f"/api/v1/projects/{project.id}/leads",
        json={"contact_name": "王同学", "contact_phone": "13800000002", "lead_source": "验收"},
        headers=auth(lead_user),
    )
    assert created.status_code == 201

    listed = client.get(f"/api/v1/projects/{project.id}/leads", headers=auth(lead_user))
    assert listed.status_code == 200
    assert listed.json()["data"][0]["contact_name"] == "王同学"


def test_05_viewer_writes_denied_and_export_audited(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"acc5-{uuid.uuid4().hex[:6]}")
    team = make_team(project, user_factory, member_factory)
    viewer = team[RoleCode.VIEWER]
    version = make_content(db, project)
    task = make_publish_task(db, project)

    # 只读角色对所有写接口都必须是 403
    write_calls = [
        ("patch", f"/api/v1/projects/{project.id}/content-versions/{version.id}/body", {"body": "只读用户想改正文"}),
        ("post", f"/api/v1/projects/{project.id}/contents", {"title": "只读用户建母稿"}),
        ("post", f"/api/v1/projects/{project.id}/content-versions/{version.id}/review", {"decision": "approved"}),
        ("post", f"/api/v1/projects/{project.id}/publish/tasks/{task.id}/attempts", {"result": "success"}),
        ("post", f"/api/v1/projects/{project.id}/leads", {"contact_name": "只读用户写的线索"}),
        ("post", f"/api/v1/projects/{project.id}/members", {"user_id": str(uuid.uuid4()), "role_code": "viewer"}),
    ]
    for method, path, payload in write_calls:
        resp = getattr(client, method)(path, json=payload, headers=auth(viewer))
        assert resp.status_code == 403, path
        assert resp.json()["error"]["code"] == "insufficient_permission", path

    exported = client.get(f"/api/v1/projects/{project.id}/channels/export", headers=auth(viewer))
    assert exported.status_code == 200
    assert "text/csv" in exported.headers["content-type"]

    audit = db.scalars(
        select(AuditLog).where(AuditLog.action == "export", AuditLog.project_id == project.id)
    ).all()
    assert audit, "导出必须写审计"
    assert (audit[-1].payload or {}).get("row_count") is not None


def test_06_reviewer_cannot_edit_body_but_can_approve(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"acc6-{uuid.uuid4().hex[:6]}")
    team = make_team(project, user_factory, member_factory)
    reviewer = team[RoleCode.REVIEWER]
    version = make_content(db, project)
    original_body = version.body

    denied = client.patch(
        f"/api/v1/projects/{project.id}/content-versions/{version.id}/body",
        json={"body": "审核人员改正文"},
        headers=auth(reviewer),
    )
    assert denied.status_code == 403
    assert version.body == original_body, "被拒绝的请求不能改动正文"

    approved = client.post(
        f"/api/v1/projects/{project.id}/content-versions/{version.id}/review",
        json={"decision": "approved", "comment": "内容与事实页一致，可签发"},
        headers=auth(reviewer),
    )
    assert approved.status_code == 200
    db.refresh(version)
    assert version.status == ContentStatus.APPROVED

    audit = db.scalars(
        select(AuditLog).where(AuditLog.action == "content.review", AuditLog.project_id == project.id)
    ).all()
    assert audit and (audit[-1].payload or {}).get("content_hash_snapshot") == version.content_hash


def test_07_editor_cannot_review_but_can_write(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"acc7-{uuid.uuid4().hex[:6]}")
    team = make_team(project, user_factory, member_factory)
    editor = team[RoleCode.EDITOR]
    version = make_content(db, project)
    task = make_publish_task(db, project)

    review_denied = client.post(
        f"/api/v1/projects/{project.id}/content-versions/{version.id}/review",
        json={"decision": "approved"},
        headers=auth(editor),
    )
    assert review_denied.status_code == 403

    body_ok = client.patch(
        f"/api/v1/projects/{project.id}/content-versions/{version.id}/body",
        json={"body": "编辑修改后的正文", "change_note": "补充课程信息"},
        headers=auth(editor),
    )
    assert body_ok.status_code == 200

    check_q = client.get(f"/api/v1/projects/{project.id}/monitoring/tasks", headers=auth(editor))
    assert check_q.status_code == 200

    attempt = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task.id}/attempts",
        json={"result": "success", "mode": "manual"},
        headers=auth(editor),
    )
    assert attempt.status_code == 201

    # 已进入 publishing，再次新增尝试必须被拒绝
    again = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task.id}/attempts",
        json={"result": "success"},
        headers=auth(editor),
    )
    assert again.status_code == 409


def test_08_cross_project_denied_for_all_resource_types(
    client, db, two_projects, user_factory, member_factory
):
    p1, p2 = two_projects
    outsider = user_factory(f"out-{uuid.uuid4().hex[:6]}")
    member_factory(p2, outsider, RoleCode.PROJECT_ADMIN)

    evidence = EvidenceFile(
        project_id=p1.id, storage_key="cross.png", file_type=EvidenceFileType.SCREENSHOT
    )
    event = OutboxEvent(project_id=p1.id, topic="publish.execute", payload={"project_id": str(p1.id)})
    db.add_all([evidence, event])
    db.flush()

    for path in (
        f"/api/v1/projects/{p1.id}/leads",
        f"/api/v1/projects/{p1.id}/channels/export",
        f"/api/v1/projects/{p1.id}/channels",
        f"/api/v1/projects/{p1.id}/evidence/{evidence.id}/download",
        f"/api/v1/tasks/{event.id}",
    ):
        resp = client.get(path, headers=auth(outsider))
        assert resp.status_code == 403, path
        assert resp.json()["error"]["code"] == "project_forbidden", path


def test_09_audit_trail_covers_key_actions(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"acc9-{uuid.uuid4().hex[:6]}")
    team = make_team(project, user_factory, member_factory)
    newcomer = user_factory(f"m-{uuid.uuid4().hex[:6]}")
    version = make_content(db, project)

    client.post(
        f"/api/v1/projects/{project.id}/members",
        json={"user_id": str(newcomer.id), "role_code": "viewer"},
        headers=auth(team[RoleCode.PROJECT_ADMIN]),
    )
    client.get(f"/api/v1/projects/{project.id}/channels/export", headers=auth(team[RoleCode.VIEWER]))
    client.post(
        f"/api/v1/projects/{project.id}/content-versions/{version.id}/review",
        json={"decision": "approved"},
        headers=auth(team[RoleCode.REVIEWER]),
    )
    client.post(f"/api/v1/projects/{project.id}/leads", json={}, headers=auth(team[RoleCode.VIEWER]))

    # 系统级动作：建项目也必须留痕
    sys_admin = team["sys_admin"]
    client.post(
        "/api/v1/projects",
        json={"code": f"audit-{uuid.uuid4().hex[:6]}", "name": "审计用项目"},
        headers=auth(sys_admin),
    )

    actions = {
        row.action
        for row in db.scalars(select(AuditLog).where(AuditLog.project_id == project.id)).all()
    }
    assert {"permission_change", "export", "content.review", "permission_denied"} <= actions
    # 系统级动作也必须留痕（建项目审计挂在新建项目 id 上）
    assert db.scalar(select(AuditLog).where(AuditLog.action == "project.create")) is not None
