"""GEO 内部验收指标 HTTP 契约测试：空项目口径、权限与筛选参数。"""

import uuid

from app.core.security import create_access_token
from app.models.enums import RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_geo_stats_empty_project_reports_technical_baseline(
    client, project_factory, user_factory, member_factory
):
    project = project_factory(f"geo-stats-{uuid.uuid4().hex[:6]}")
    viewer = user_factory(f"viewer-{uuid.uuid4().hex[:6]}")
    member_factory(project, viewer, RoleCode.VIEWER)

    response = client.get(
        f"/api/v1/projects/{project.id}/stats/geo",
        headers=_auth(viewer),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["valid_answers"] == 0
    assert data["mention_rate"] is None
    assert data["citation_share"] is None
    assert data["sov"] is None
    assert data["freshness_hours"] is None
    assert data["failure_rate"] is None
    assert data["counts"]["total_samples"] == 0
    assert data["by_competitor"] == []
    assert data["definitions"]["mention_rate"] == "brand_mentioned_answers / valid_answers"
    assert "技术链路基线" in data["statement"]


def test_geo_stats_filters_and_scope(
    client, project_factory, user_factory, member_factory
):
    project = project_factory(f"geo-stats-filter-{uuid.uuid4().hex[:6]}")
    viewer = user_factory(f"viewer-{uuid.uuid4().hex[:6]}")
    outsider = user_factory(f"outsider-{uuid.uuid4().hex[:6]}")
    member_factory(project, viewer, RoleCode.VIEWER)

    response = client.get(
        f"/api/v1/projects/{project.id}/stats/geo",
        params={"round_id": str(uuid.uuid4())},
        headers=_auth(viewer),
    )
    assert response.status_code == 200
    assert response.json()["data"]["valid_answers"] == 0

    forbidden = client.get(
        f"/api/v1/projects/{project.id}/stats/geo",
        headers=_auth(outsider),
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "project_forbidden"
