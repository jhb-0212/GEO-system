"""客户级设置：继承、配额、客户策略，全部是显式开关。"""

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import Project, ProjectMember, Role
from app.models.enums import RoleCode
from app.services.industry_presets import project_industry_config, upsert_strategy
from app.services.organization_settings import get_settings


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_settings_are_sys_admin_only(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"orgset-{suffix}")
    admin = user_factory(f"orgset-admin-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)

    denied = client.get(f"/api/v1/projects/{project.id}/organization", headers=_auth(admin))
    assert denied.status_code == 403

    root = user_factory(f"orgset-root-{suffix}", is_system_admin=True)
    got = client.get(f"/api/v1/projects/{project.id}/organization", headers=_auth(root)).json()["data"]
    assert got["inherit_members"] is False
    assert got["quotas"] == {
        "projects": None, "members": None, "project_members": None, "consumption": {}
    }
    assert got["alerts"] == []
    assert got["usage"]["project_members"] >= 1

    trend = client.get(
        f"/api/v1/projects/{project.id}/organization/usage?days=7", headers=_auth(root)
    ).json()["data"]
    assert len(trend["series"]) == 7
    assert trend["series"][-1]["projects"] >= 1


def test_project_quota_blocks_before_creating(client, db, project_factory, user_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"orgq-{suffix}")
    root = user_factory(f"orgq-root-{suffix}", is_system_admin=True)
    used = get_settings(db, project.organization_id)["usage"]["projects"]

    client.put(
        f"/api/v1/projects/{project.id}/organization",
        headers=_auth(root),
        json={"quotas": {"projects": used}},
    )
    blocked = client.post(
        "/api/v1/projects", headers=_auth(root),
        json={"code": f"orgq-{suffix}-x", "name": "超额项目"},
    )
    assert blocked.status_code == 400
    assert blocked.json()["error"]["code"] == "organization_project_quota_exceeded"

    client.put(
        f"/api/v1/projects/{project.id}/organization",
        headers=_auth(root),
        json={"quotas": {"projects": used + 1}},
    )
    created = client.post(
        "/api/v1/projects", headers=_auth(root),
        json={"code": f"orgq-{suffix}-y", "name": "配额内项目"},
    )
    assert created.status_code == 201, created.text


def test_member_and_project_member_quotas(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"orgmq-{suffix}")
    root = user_factory(f"orgmq-root-{suffix}", is_system_admin=True)
    admin = user_factory(f"orgmq-admin-{suffix}")
    newbie = user_factory(f"orgmq-new-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)

    org_used = get_settings(db, project.organization_id)["usage"]["members"]
    client.put(
        f"/api/v1/projects/{project.id}/organization",
        headers=_auth(root),
        json={"quotas": {"members": org_used}},
    )
    blocked = client.post(
        f"/api/v1/projects/{project.id}/organization-members",
        headers=_auth(admin),
        json={"user_id": str(newbie.id)},
    )
    assert blocked.status_code == 400
    assert blocked.json()["error"]["code"] == "organization_member_quota_exceeded"

    client.put(
        f"/api/v1/projects/{project.id}/organization",
        headers=_auth(root),
        json={"quotas": {"members": org_used + 5, "project_members": 1}},
    )
    assert client.post(
        f"/api/v1/projects/{project.id}/organization-members",
        headers=_auth(admin), json={"user_id": str(newbie.id)},
    ).status_code == 200

    too_many = client.post(
        f"/api/v1/projects/{project.id}/members",
        headers=_auth(admin), json={"user_id": str(newbie.id), "role_code": "viewer"},
    )
    assert too_many.status_code == 400
    assert too_many.json()["error"]["code"] == "organization_project_member_quota_exceeded"


def test_inherit_members_only_when_enabled(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"orgi-{suffix}")
    root = user_factory(f"orgi-root-{suffix}", is_system_admin=True)
    admin = user_factory(f"orgi-admin-{suffix}")
    teammate = user_factory(f"orgi-mate-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    client.post(
        f"/api/v1/projects/{project.id}/organization-members",
        headers=_auth(admin), json={"user_id": str(teammate.id)},
    )

    # 默认关闭：新项目不继承
    off = client.post(
        "/api/v1/projects", headers=_auth(root),
        json={"code": f"orgi-{suffix}-a", "name": "不继承"},
    ).json()["data"]
    assert db.scalar(select(ProjectMember).where(
        ProjectMember.project_id == uuid.UUID(off["id"]), ProjectMember.user_id == teammate.id
    )) is None

    client.put(
        f"/api/v1/projects/{project.id}/organization", headers=_auth(root), json={"inherit_members": True}
    )
    on = client.post(
        "/api/v1/projects", headers=_auth(root),
        json={"code": f"orgi-{suffix}-b", "name": "继承名册"},
    ).json()["data"]
    inherited = db.scalar(select(ProjectMember).where(
        ProjectMember.project_id == uuid.UUID(on["id"]), ProjectMember.user_id == teammate.id
    ))
    assert inherited is not None and inherited.is_active


def test_customer_strategy_merges_between_preset_and_project(client, db, project_factory, user_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"orgs-{suffix}")
    root = user_factory(f"orgs-root-{suffix}", is_system_admin=True)

    client.put(
        f"/api/v1/projects/{project.id}/organization",
        headers=_auth(root),
        json={"strategy": {"quality": {"absolute_claims": ["客户自定义绝对词"]}}},
    )
    config = project_industry_config(db, project.id)
    assert "客户自定义绝对词" in config["quality"]["absolute_claims"]

    # 项目策略优先于客户策略
    upsert_strategy(db, project.id, preset_code="edu-training", overrides={
        "quality": {"absolute_claims": ["项目覆盖词"]},
    })
    db.flush()
    config = project_industry_config(db, project.id)
    assert config["quality"]["absolute_claims"] == ["项目覆盖词"]


def test_quota_alert_at_eighty_percent(client, db, project_factory, user_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"orgw-{suffix}")
    root = user_factory(f"orgw-root-{suffix}", is_system_admin=True)
    used = get_settings(db, project.organization_id, project.id)["usage"]["projects"]

    client.put(
        f"/api/v1/projects/{project.id}/organization", headers=_auth(root),
        json={"quotas": {"projects": used}},
    )
    data = client.get(f"/api/v1/projects/{project.id}/organization", headers=_auth(root)).json()["data"]
    assert any(item["level"] in ("warning", "exceeded") for item in data["alerts"])


def test_inherit_members_role_is_configurable(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"orgir-{suffix}")
    root = user_factory(f"orgir-root-{suffix}", is_system_admin=True)
    admin = user_factory(f"orgir-admin-{suffix}")
    teammate = user_factory(f"orgir-mate-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    client.post(
        f"/api/v1/projects/{project.id}/organization-members",
        headers=_auth(admin), json={"user_id": str(teammate.id)},
    )
    updated = client.put(
        f"/api/v1/projects/{project.id}/organization",
        headers=_auth(root), json={"inherit_members": True, "inherit_role": "editor"},
    )
    assert updated.status_code == 200, updated.text

    created = client.post(
        "/api/v1/projects", headers=_auth(root),
        json={"code": f"orgir-{suffix}-b", "name": "继承编辑角色"},
    ).json()["data"]
    inherited = db.scalar(select(ProjectMember).where(
        ProjectMember.project_id == uuid.UUID(created["id"]), ProjectMember.user_id == teammate.id
    ))
    assert inherited is not None
    assert db.get(Role, inherited.role_id).code == "editor"

    invalid = client.put(
        f"/api/v1/projects/{project.id}/organization",
        headers=_auth(root), json={"inherit_role": "project_admin"},
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "organization_settings_invalid"


def test_usage_trend_uses_daily_snapshot(client, db, project_factory, user_factory):
    from datetime import datetime, timezone

    from app.models import OrganizationUsageSnapshot
    from app.services.organization_settings import capture_usage_snapshots

    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"orgsnap-{suffix}")
    root = user_factory(f"orgsnap-root-{suffix}", is_system_admin=True)
    today = datetime.now(timezone.utc).date()
    capture_usage_snapshots(db, on_date=today)
    snapshot = db.scalar(select(OrganizationUsageSnapshot).where(
        OrganizationUsageSnapshot.organization_id == project.organization_id,
        OrganizationUsageSnapshot.captured_on == today,
    ))
    assert snapshot is not None and snapshot.projects >= 1

    trend = client.get(
        f"/api/v1/projects/{project.id}/organization/usage?days=3", headers=_auth(root)
    ).json()["data"]
    assert trend["series"][-1]["source"] == "snapshot"
    assert trend["snapshot_days"] >= 1
