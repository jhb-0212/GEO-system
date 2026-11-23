"""项目口径配置：通用默认 + 项目覆盖（全部测试数据，不碰真实库）。"""

import uuid

from app.core.security import create_access_token
from app.models.enums import RoleCode
from app.services.project_policy import DEFAULTS, effective_policies


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_defaults_are_generic_and_projects_are_isolated(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project_a = project_factory(f"policy-a-{suffix}")
    project_b = project_factory(f"policy-b-{suffix}")
    admin = user_factory(f"policy-admin-{suffix}")
    member_factory(project_a, admin, RoleCode.PROJECT_ADMIN)
    member_factory(project_b, admin, RoleCode.PROJECT_ADMIN)

    base_a = f"/api/v1/projects/{project_a.id}/"
    base_b = f"/api/v1/projects/{project_b.id}/"

    assert client.get(f"{base_a}stats/policies", headers=_auth(admin)).json()["data"] == DEFAULTS

    put = client.put(
        f"{base_a}stats/policies",
        headers=_auth(admin),
        json={
            "policies": {
                "freshness.window_months": 6,
                "contract.target_streak": 10,
                "sentiment.min_report": 20,
                "quality.number_level": "block",
            },
            "notes": {"freshness.window_months": "客户要求半年内内容才算新"},
        },
    )
    assert put.status_code == 200, put.text
    data = put.json()["data"]
    assert data["changed"] == 4
    assert data["effective"]["freshness.window_months"] == 6
    assert data["effective"]["quality.number_level"] == "block"

    # 项目 B 不受影响：仍然全是通用默认
    assert client.get(f"{base_b}stats/policies", headers=_auth(admin)).json()["data"] == DEFAULTS
    assert effective_policies(db, project_b.id)["contract.target_streak"] == 30


def test_policy_drives_stats_endpoints(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"policy-stats-{suffix}")
    admin = user_factory(f"policy-stats-admin-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    base = f"/api/v1/projects/{project.id}/"

    fresh_default = client.get(f"{base}stats/content-freshness", headers=_auth(admin)).json()["data"]
    assert fresh_default["window_months"] == 18

    client.put(
        f"{base}stats/policies",
        headers=_auth(admin),
        json={"policies": {"freshness.window_months": 9, "contract.target_streak": 7}},
    )
    fresh = client.get(f"{base}stats/content-freshness", headers=_auth(admin)).json()["data"]
    assert fresh["window_months"] == 9

    contract = client.get(f"{base}stats/acceptance-contract", headers=_auth(admin)).json()["data"]
    assert contract["streak"]["target"] == 7

    # 显式传参优先于项目口径，便于一次性核对
    explicit = client.get(f"{base}stats/content-freshness?months=3", headers=_auth(admin)).json()["data"]
    assert explicit["window_months"] == 3


def test_invalid_policy_is_reported_not_applied(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"policy-bad-{suffix}")
    admin = user_factory(f"policy-bad-admin-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)

    resp = client.put(
        f"/api/v1/projects/{project.id}/stats/policies",
        headers=_auth(admin),
        json={"policies": {"nonsense.key": 1, "quality.quote_level": "hard", "freshness.window_months": -2}},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    statuses = {item["key"]: item["status"] for item in data["decisions"]}
    assert statuses == {"nonsense.key": "invalid", "quality.quote_level": "invalid", "freshness.window_months": "invalid"}
    assert data["changed"] == 0
    assert data["effective"] == DEFAULTS

    # 只读角色不能改口径
    viewer = user_factory(f"policy-viewer-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)
    denied = client.put(
        f"/api/v1/projects/{project.id}/stats/policies",
        headers=_auth(viewer),
        json={"policies": {"freshness.window_months": 4}},
    )
    assert denied.status_code == 403
