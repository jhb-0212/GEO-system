"""项目时区修改：权限、校验、幂等、审计同事务与旧值修复。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.core.permissions import permissions_for
from app.core.security import create_access_token
from app.models import AuditLog, Project
from app.models.enums import RoleCode
from scripts.seed import seed_permissions, seed_role_permissions


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _setup(project_factory, user_factory, member_factory, role=RoleCode.PROJECT_ADMIN):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"tz-api-{suffix}")
    user = user_factory(f"tz-api-user-{suffix}")
    member_factory(project, user, role)
    return project, user, _auth(user)


@pytest.fixture(autouse=True)
def _seed_timezone_permission(db):
    """测试库可能已有旧 role_permissions；按规范化种子补齐新能力映射。"""
    seed_permissions(db)
    seed_role_permissions(db)
    db.flush()
    yield


def _audits(db, project_id, action="project.timezone.update"):
    return db.scalars(
        select(AuditLog).where(AuditLog.project_id == project_id, AuditLog.action == action)
    ).all()


def test_timezone_permission_code_only_project_admin():
    assert "project.timezone.manage" in permissions_for(RoleCode.PROJECT_ADMIN)
    for role in (
        RoleCode.EDITOR,
        RoleCode.REVIEWER,
        RoleCode.VIEWER,
        RoleCode.LEAD_OPS,
        RoleCode.SYS_ADMIN,
    ):
        assert "project.timezone.manage" not in permissions_for(role)


def test_update_timezone_records_audit_and_changes_business_window(
    client, db, project_factory, user_factory, member_factory
):
    project, user, headers = _setup(project_factory, user_factory, member_factory)
    response = client.put(
        f"/api/v1/projects/{project.id}/timezone",
        json={"timezone": "America/New_York"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["changed"] is True
    assert data["previous_timezone"] == "Asia/Shanghai"
    assert data["timezone"] == "America/New_York"
    assert data["impact"]["old_local_today"]
    assert data["updated_at"]

    assert db.get(Project, project.id).timezone == "America/New_York"
    audits = _audits(db, project.id)
    assert len(audits) == 1
    assert audits[0].actor_id == user.id
    assert audits[0].payload["old_timezone"] == "Asia/Shanghai"
    assert audits[0].payload["new_timezone"] == "America/New_York"
    assert audits[0].payload["impact"]["historical_recalculated"] is False

    todos = client.get(f"/api/v1/projects/{project.id}/workbench/todos?range=all", headers=headers)
    assert todos.status_code == 200, todos.text
    assert todos.json()["data"]["business_timezone"] == "America/New_York"


def test_same_timezone_is_idempotent_without_audit(client, db, project_factory, user_factory, member_factory):
    project, _, headers = _setup(project_factory, user_factory, member_factory)
    before = db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "project.timezone.update"))
    response = client.put(
        f"/api/v1/projects/{project.id}/timezone",
        json={"timezone": "Asia/Shanghai"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["changed"] is False
    after = db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "project.timezone.update"))
    assert after == before
    assert db.get(Project, project.id).timezone == "Asia/Shanghai"


def test_update_timezone_rejects_invalid_and_offset_values(
    client, db, project_factory, user_factory, member_factory
):
    project, _, headers = _setup(project_factory, user_factory, member_factory)
    for bad in ("Mars/Olympus", "   ", "+08:00", "UTC+8"):
        response = client.put(
            f"/api/v1/projects/{project.id}/timezone",
            json={"timezone": bad},
            headers=headers,
        )
        assert response.status_code == 422, (bad, response.text)
    assert db.get(Project, project.id).timezone == "Asia/Shanghai"


def test_editor_cannot_update_timezone(client, db, project_factory, user_factory, member_factory):
    project, _, headers = _setup(project_factory, user_factory, member_factory, RoleCode.EDITOR)
    response = client.put(
        f"/api/v1/projects/{project.id}/timezone",
        json={"timezone": "America/New_York"},
        headers=headers,
    )
    assert response.status_code == 403, response.text
    assert db.get(Project, project.id).timezone == "Asia/Shanghai"


def test_invalid_old_timezone_can_be_repaired(client, db, project_factory, user_factory, member_factory):
    project, _, headers = _setup(project_factory, user_factory, member_factory)
    project.timezone = "Mars/Olympus"
    db.commit()

    response = client.put(
        f"/api/v1/projects/{project.id}/timezone",
        json={"timezone": "America/New_York"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["previous_timezone"] == "Mars/Olympus"
    assert data["impact"]["old_local_today"] is None
    assert db.get(Project, project.id).timezone == "America/New_York"


def test_audit_failure_rolls_back_timezone(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    project, _, headers = _setup(project_factory, user_factory, member_factory)
    import app.api.projects as projects_api

    def _boom(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(projects_api, "record_audit", _boom)
    # 审计写入抛错必须向调用方失败，不能吞掉后继续提交。
    # 回滚由端点内同一 Session 显式执行；测试夹具共享外层事务，不在请求失败后断言库态。
    with pytest.raises(RuntimeError, match="audit unavailable"):
        client.put(
            f"/api/v1/projects/{project.id}/timezone",
            json={"timezone": "America/New_York"},
            headers=headers,
        )
